"""
p21_api_client.py -- P21 Transaction API client for direct Sales Order creation.

Replaces CISM flat-file generation with real-time API calls to Epicor Prophet 21.
Uses the Transaction API v2 to create Sales Orders programmatically.

Auth flow:
  1. POST /api/security/token/v2 → Bearer token
  2. GET /api/ui/router/v1?urlType=external → UI server URL
  3. POST {ui_server}/api/v2/transaction → Create SO

Env vars (read via config.get_settings):
  P21_BASE_URL, P21_API_USERNAME, P21_API_PASSWORD, P21_VERIFY_SSL, P21_DEFAULT_TAKER
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

P21_BASE_URL = os.environ.get("P21_BASE_URL", "")
P21_API_USERNAME = os.environ.get("P21_API_USERNAME", "")
P21_API_PASSWORD = os.environ.get("P21_API_PASSWORD", "")
P21_VERIFY_SSL = os.environ.get("P21_VERIFY_SSL", "false").lower() in ("true", "1", "yes")
P21_DEFAULT_TAKER = os.environ.get("P21_DEFAULT_TAKER", "POAGENT")
P21_DEFAULT_LOCATION = os.environ.get("P21_LOCATION_ID", "10")
P21_DEFAULT_COMPANY = os.environ.get("P21_COMPANY_ID", "1")

DYNACHANGE_ALERT_MARKER = "Dynachange Alert"


class P21ApiError(Exception):
    """Raised when the P21 Transaction API returns a failure."""

    def __init__(self, message: str, status_code: int = None, response_body: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class P21AuthError(P21ApiError):
    """Authentication failed after retry."""
    pass


class P21ApiClient:
    """
    Async client for the P21 Transaction API.

    Usage:
        client = P21ApiClient(base_url, username, password)
        result = await client.create_sales_order(po_data)
        print(result["order_no"])
    """

    def __init__(
        self,
        base_url: str = None,
        username: str = None,
        password: str = None,
        verify_ssl: bool = None,
    ):
        self.base_url = (base_url or P21_BASE_URL).rstrip("/")
        self.username = username or P21_API_USERNAME
        self.password = password or P21_API_PASSWORD
        self.verify_ssl = verify_ssl if verify_ssl is not None else P21_VERIFY_SSL

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._ui_server_url: Optional[str] = None
        self._order_schema: Optional[dict] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=httpx.Timeout(60.0, connect=15.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Authentication ────────────────────────────────────────────────

    async def authenticate(self) -> str:
        """
        POST /api/security/token/v2 to get a bearer token.
        Caches the token and auto-refreshes when expired.
        Returns the access token string.
        """
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        url = f"{self.base_url}/api/security/token/v2"
        payload = {"username": self.username, "password": self.password}

        logger.info("P21 API: authenticating as %s against %s", self.username, self.base_url)

        client = await self._get_client()
        resp = await client.post(url, json=payload)

        if resp.status_code != 200:
            logger.error("P21 auth failed: %s %s", resp.status_code, resp.text[:500])
            raise P21AuthError(
                f"P21 authentication failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        data = resp.json()
        self._access_token = data["AccessToken"]
        expires_in = data.get("ExpiresInSeconds", 86400)
        self._token_expires_at = time.time() + expires_in

        logger.info("P21 API: authenticated, token expires in %ds", expires_in)
        return self._access_token

    async def _auth_headers(self) -> dict:
        token = await self.authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request_with_reauth(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Make a request; on 401, re-authenticate once and retry."""
        client = await self._get_client()
        headers = await self._auth_headers()
        kwargs.setdefault("headers", {}).update(headers)

        resp = await client.request(method, url, **kwargs)

        if resp.status_code == 401:
            logger.warning("P21 API: got 401, re-authenticating")
            self._access_token = None
            self._token_expires_at = 0
            headers = await self._auth_headers()
            kwargs["headers"].update(headers)
            resp = await client.request(method, url, **kwargs)

            if resp.status_code == 401:
                raise P21AuthError(
                    "P21 authentication failed after re-auth attempt",
                    status_code=401,
                )

        return resp

    # ── UI Server Discovery ───────────────────────────────────────────

    async def discover_ui_server(self) -> str:
        """
        GET /api/ui/router/v1?urlType=external to get the UI server URL.
        The Transaction API create endpoint lives on the UI server, not the base URL.
        Caches the result.
        """
        if self._ui_server_url:
            return self._ui_server_url

        url = f"{self.base_url}/api/ui/router/v1"
        resp = await self._request_with_reauth("GET", url, params={"urlType": "external"})

        if resp.status_code != 200:
            raise P21ApiError(
                f"UI server discovery failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        data = resp.json()
        self._ui_server_url = data.get("Url", "").rstrip("/")

        if not self._ui_server_url:
            raise P21ApiError("UI server discovery returned empty URL")

        logger.info("P21 API: UI server = %s", self._ui_server_url)
        return self._ui_server_url

    # ── Ping / Health Check ───────────────────────────────────────────

    async def ping(self) -> dict:
        """Lightweight check — auth only, no SO creation."""
        try:
            await self.authenticate()
            return {"status": "connected"}
        except P21AuthError as e:
            return {"status": "auth_failed", "error": str(e)}
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}
        finally:
            await self.close()

    # ── Order Schema (optional) ───────────────────────────────────────

    async def get_order_schema(self) -> dict:
        """
        GET /api/v2/definition/Order — returns the full Transaction API
        schema for the Order service. Useful for field discovery.
        Caches the result.
        """
        if self._order_schema:
            return self._order_schema

        ui_url = await self.discover_ui_server()
        url = f"{ui_url}/api/v2/definition/Order"

        resp = await self._request_with_reauth("GET", url)

        if resp.status_code != 200:
            raise P21ApiError(
                f"Order schema fetch failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
            )

        self._order_schema = resp.json()
        logger.info("P21 API: order schema cached (%d bytes)", len(resp.content))
        return self._order_schema

    # ── Create Sales Order ────────────────────────────────────────────

    async def create_sales_order(self, po_data: dict) -> dict:
        """
        Create a Sales Order from approved PO data.

        Args:
            po_data: dict with keys: header, lines, customer_match, customer_defaults

        Returns:
            {"order_no": "456789", "status": "Passed", "raw_response": {...}}
        """
        ui_url = await self.discover_ui_server()
        url = f"{ui_url}/api/v2/transaction"

        payload = self._build_order_payload(po_data)

        logger.info(
            "P21 API: creating SO for customer=%s po=%s lines=%d",
            po_data.get("customer_match", {}).get("p21_customer_id", "?"),
            po_data.get("header", {}).get("po_no", "?"),
            len(po_data.get("lines", [])),
        )

        resp = await self._request_with_reauth("POST", url, json=payload)

        if resp.status_code not in (200, 201):
            raise P21ApiError(
                f"Create SO failed (HTTP {resp.status_code}): {resp.text[:500]}",
                status_code=resp.status_code,
                response_body=self._safe_json(resp),
            )

        body = resp.json()
        return self._parse_create_response(body, po_data)

    async def create_sales_orders_batch(self, po_list: list[dict]) -> list[dict]:
        """
        Bulk create — sends multiple transactions in one API request.
        Each po_data in po_list becomes a separate Transaction entry.

        Returns list of result dicts, one per PO.
        """
        if not po_list:
            return []

        ui_url = await self.discover_ui_server()
        url = f"{ui_url}/api/v2/transaction"

        transactions = []
        for po_data in po_list:
            single_payload = self._build_order_payload(po_data)
            transactions.extend(single_payload["Transactions"])

        batch_payload = {
            "Name": "Order",
            "UseCodeValues": False,
            "Transactions": transactions,
        }

        logger.info("P21 API: batch creating %d sales orders", len(po_list))

        resp = await self._request_with_reauth("POST", url, json=batch_payload)

        if resp.status_code not in (200, 201):
            raise P21ApiError(
                f"Batch create failed (HTTP {resp.status_code}): {resp.text[:500]}",
                status_code=resp.status_code,
                response_body=self._safe_json(resp),
            )

        body = resp.json()
        results = []
        response_txns = (
            body.get("Results", {}).get("Transactions", [])
            if "Results" in body
            else body.get("Transactions", [])
        )

        for i, po_data in enumerate(po_list):
            if i < len(response_txns):
                txn = response_txns[i]
                results.append(self._parse_single_transaction(txn, po_data))
            else:
                results.append({
                    "order_no": None,
                    "status": "Unknown",
                    "error": "No matching transaction in response",
                    "po_no": po_data.get("header", {}).get("po_no", ""),
                })

        summary = body.get("Summary", {})
        logger.info(
            "P21 API: batch complete — succeeded=%s failed=%s",
            summary.get("Succeeded", "?"),
            summary.get("Failed", "?"),
        )

        return results

    # ── Payload Builder ───────────────────────────────────────────────

    def _build_order_payload(self, po_data: dict) -> dict:
        """
        Map po_data (same structure as cism_so_generator consumes)
        to the P21 Transaction API payload format.

        po_data keys:
          header: dict with po_no, order_date, ship_to_id_p21, etc.
          lines: list of line dicts
          customer_match: dict with p21_customer_id
          customer_defaults: dict with ship_to_id, carrier_id, contact_id, terms
        """
        header = po_data.get("header", {})
        lines = po_data.get("lines", [])
        customer = po_data.get("customer_match", {})
        defaults = po_data.get("customer_defaults", {})

        order_date = self._to_p21_date(header.get("order_date", ""))
        if not order_date:
            order_date = datetime.utcnow().strftime("%m/%d/%Y")

        first_line_date = None
        if lines:
            first_line_date = self._to_p21_date(lines[0].get("required_date", ""))
        requested_date = first_line_date or order_date

        # Build header edits from available data; P21 Transaction API v2 accepts
        # these fields and will apply customer-master defaults for any omitted values.
        # Field list derived from template verification/p21_payload_template.json.
        # NOTE: Official P21 docs should be consulted to confirm required vs optional.
        ship_to_id = defaults.get("ship_to_id") or defaults.get("default_address_id") or header.get("ship_to_id_p21", "")
        carrier_id = defaults.get("carrier_id") or defaults.get("default_carrier_id", "")
        contact_id = defaults.get("contact_id") or defaults.get("default_contact_id", "")
        terms_id = defaults.get("terms") or defaults.get("terms_id") or defaults.get("default_terms", "")

        header_edits_raw = [
            {"Name": "customer_id", "Value": str(customer.get("p21_id") or customer.get("p21_customer_id", ""))},
            {"Name": "po_no", "Value": str(header.get("po_no", ""))[:50]},
            {"Name": "ship_to_id", "Value": str(ship_to_id)},
            {"Name": "order_date", "Value": order_date},
            {"Name": "requested_date", "Value": requested_date},
            {"Name": "source_location_id", "Value": str(defaults.get("source_location_id", P21_DEFAULT_LOCATION))},
            {"Name": "carrier_id", "Value": str(carrier_id)},
            {"Name": "approved", "Value": "Y"},
            {"Name": "company_id", "Value": str(defaults.get("company_id", P21_DEFAULT_COMPANY))},
            {"Name": "contact_id", "Value": str(contact_id)},
            {"Name": "taker", "Value": str(defaults.get("taker", P21_DEFAULT_TAKER))},
            {"Name": "terms_id", "Value": str(terms_id)},
            {"Name": "quote", "Value": "OFF"},
        ]
        header_edits = [e for e in header_edits_raw if e["Value"] not in ("", None)]

        item_rows = []
        for i, line in enumerate(lines, start=1):
            item_id = line.get("item_id_p21") or line.get("supplier_part_id", "")
            line_date = self._to_p21_date(
                line.get("required_date") or line.get("date_due", "")
            ) or order_date

            item_edits_raw = [
                {"Name": "oe_order_item_id", "Value": str(item_id)},
                {"Name": "unit_quantity", "Value": f"{float(line.get('qty_ordered', 0)):.9f}"},
                {"Name": "unit_price", "Value": f"{float(line.get('unit_price', 0)):.4f}"},
                {"Name": "source_loc_id", "Value": str(defaults.get("source_location_id", P21_DEFAULT_LOCATION))},
                {"Name": "line_no", "Value": str(line.get("line_no", i))},
                {"Name": "required_date", "Value": line_date},
            ]
            item_edits = [e for e in item_edits_raw if e["Value"] not in ("", None)]

            item_rows.append({
                "Edits": item_edits,
                "RelativeDateEdits": [],
            })

        return {
            "Name": "Order",
            "UseCodeValues": False,
            "Transactions": [
                {
                    "Status": "New",
                    "DataElements": [
                        {
                            "Name": "TABPAGE_1.order",
                            "Type": "Form",
                            "Keys": [],
                            "Rows": [
                                {
                                    "Edits": header_edits,
                                    "RelativeDateEdits": [],
                                }
                            ],
                        },
                        {
                            "Name": "TP_ITEMS.items",
                            "Type": "List",
                            "Keys": [],
                            "Rows": item_rows,
                        },
                    ],
                }
            ],
        }

    # ── Response Parsing ──────────────────────────────────────────────

    def _parse_create_response(self, body: dict, po_data: dict) -> dict:
        """Parse the Transaction API response for a single-SO create."""
        transactions = (
            body.get("Results", {}).get("Transactions", [])
            if "Results" in body
            else body.get("Transactions", [])
        )

        if not transactions:
            raise P21ApiError(
                "P21 response contained no transactions",
                response_body=body,
            )

        txn = transactions[0]
        result = self._parse_single_transaction(txn, po_data)
        result["raw_response"] = body

        summary = body.get("Summary", {})
        if summary.get("Failed", 0) > 0:
            logger.error("P21 API: SO creation reported failure — %s", summary)

        return result

    def _parse_single_transaction(self, txn: dict, po_data: dict) -> dict:
        """Extract order_no and status from a single transaction result."""
        status = txn.get("Status", "Unknown")
        po_no = po_data.get("header", {}).get("po_no", "")
        order_no = None
        errors = []

        for elem in txn.get("DataElements", []):
            if elem.get("Name") == "TABPAGE_1.order":
                for row in elem.get("Rows", []):
                    for edit in row.get("Edits", []):
                        if edit.get("Name") == "order_no":
                            order_no = edit.get("Value")

            if DYNACHANGE_ALERT_MARKER in elem.get("Name", ""):
                logger.warning(
                    "P21 API: DynaChange Alert triggered for PO %s. "
                    "Consider using a service account with no DynaChange rules configured.",
                    po_no,
                )
                errors.append("DynaChange Alert window encountered")

        for err in txn.get("Errors", []):
            errors.append(err.get("Message", str(err)))

        if status == "Passed" and order_no:
            logger.info("P21 API: SO created — order_no=%s po=%s", order_no, po_no)
        elif status == "Failed":
            logger.error("P21 API: SO creation failed for PO %s — %s", po_no, errors)
        else:
            logger.warning(
                "P21 API: SO status=%s order_no=%s po=%s errors=%s",
                status, order_no, po_no, errors,
            )

        result = {
            "order_no": order_no,
            "status": status,
            "po_no": po_no,
            "customer_id": po_data.get("customer_match", {}).get("p21_id") or po_data.get("customer_match", {}).get("p21_customer_id", ""),
        }
        if errors:
            result["errors"] = errors

        return result

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _to_p21_date(date_str: str) -> str:
        """Convert various date formats to MM/DD/YYYY for the P21 Transaction API."""
        if not date_str:
            return ""
        date_str = str(date_str).strip()
        if len(date_str) >= 10 and date_str[4] == "-":
            try:
                dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                return dt.strftime("%m/%d/%Y")
            except ValueError:
                logger.warning(f"_to_p21_date: unrecognized YYYY-MM-DD variant '{date_str}', returning empty")
                return ""
        if len(date_str) >= 10 and date_str[2] == "/":
            return date_str[:10]
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "").split("T")[0])
            return dt.strftime("%m/%d/%Y")
        except (ValueError, AttributeError):
            logger.warning(f"_to_p21_date: unrecognized date format '{date_str}', returning empty")
            return ""

    def generate_payload_json(self, po_data: dict) -> str:
        """Generate the P21 Transaction API payload as formatted JSON for manual testing."""
        import json
        payload = self._build_order_payload(po_data)
        return json.dumps(payload, indent=2)

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Optional[dict]:
        try:
            return resp.json()
        except Exception:
            return None


def build_p21_payload(po_data: dict) -> dict:
    """Build a P21 Transaction API payload from po_data. No client needed."""
    client = P21ApiClient.__new__(P21ApiClient)
    return client._build_order_payload(po_data)


def build_p21_payload_json(po_data: dict) -> str:
    """Build a P21 Transaction API payload as formatted JSON. No client needed."""
    import json
    return json.dumps(build_p21_payload(po_data), indent=2)
