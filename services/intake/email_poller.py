"""
email_poller.py — Microsoft Graph API email polling service.

Polls orders@enproinc.com for new PO emails, detects attachment type,
routes to the correct parser, then runs the full crosswalk → confidence →
CISM → local-store pipeline (identical to the /api/v1/intake/upload flow).

Supported attachment types:
  .pdf          → Azure Document Intelligence  (primary — real POs arrive this way)
  .xml / .cxml  → cXML parser                 (Ariba / Coupa EDI)
  .csv          → CSV PO parser               (internal / bulk uploads)

Anything else is logged and skipped.
"""

import os
import base64
import asyncio
import logging
import random
import tempfile
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import aiohttp
from services.intake.email_classifier import classify_email, EmailClassification


# ── Configuration ─────────────────────────────────────────────────────────────

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MAILBOX        = os.environ.get("GRAPH_MAILBOX", "orders@enproinc.com")

TENANT_ID     = os.environ.get("AZURE_TENANT_ID")     or os.environ.get("GRAPH_TENANT_ID",     "")
CLIENT_ID     = os.environ.get("AZURE_CLIENT_ID")     or os.environ.get("GRAPH_CLIENT_ID",     "")
CLIENT_SECRET = os.environ.get("AZURE_CLIENT_SECRET") or os.environ.get("GRAPH_CLIENT_SECRET", "")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL", "60"))

INBOX_FOLDER      = "inbox"
PROCESSED_FOLDER  = "Processed-PO"
WATERMARK_FILE    = os.path.join("data", "last_poll_watermark.txt")


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class EmailAttachment:
    name: str
    content_type: str
    content_bytes: bytes
    size: int


@dataclass
class EmailMessage:
    message_id: str
    subject: str
    sender_email: str
    sender_name: str
    received_at: datetime
    body_preview: str
    has_attachments: bool
    attachments: List[EmailAttachment]
    classification: Optional[EmailClassification] = None


# ── Graph API helpers ─────────────────────────────────────────────────────────

async def _graph_api_request(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    data: Optional[Any] = None,
    max_retries: int = 3,
    return_bytes: bool = False,
) -> Any:
    """HTTP request with exponential-backoff retry and jitter."""
    logger = logging.getLogger(__name__)
    for attempt in range(max_retries + 1):
        try:
            async with session.request(
                method, url, headers=headers, json=json, data=data
            ) as resp:
                if resp.status == 429:
                    wait = int(resp.headers.get("Retry-After") or (2 ** attempt))
                    wait += random.uniform(0, 0.5)
                    logger.warning(f"Graph 429 — retrying {url} in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue

                if resp.status >= 500:
                    if attempt < max_retries:
                        wait = (2 ** attempt) + random.uniform(0, 0.5)
                        logger.warning(f"Graph {resp.status} — retrying {url} in {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue

                if resp.status >= 400:
                    raise Exception(f"Graph API error {resp.status}: {await resp.text()}")

                if resp.status == 204:
                    return {}

                return (await resp.read()) if return_bytes else (await resp.json())

        except (asyncio.TimeoutError, aiohttp.ClientConnectorError) as exc:
            if attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(f"Graph request error ({type(exc).__name__}) — retry in {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            raise

    raise Exception(f"Graph API failed after {max_retries} retries: {url}")


# ── Microsoft Graph Client ────────────────────────────────────────────────────

class GraphClient:
    def __init__(self):
        self.access_token: Optional[str] = None
        self.token_expires: Optional[datetime] = None
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        await self._ensure_token()
        return self

    async def __aexit__(self, *_):
        if self.session:
            await self.session.close()

    async def _ensure_token(self) -> str:
        if self.access_token and self.token_expires and datetime.utcnow() < self.token_expires:
            return self.access_token

        if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
            raise ValueError(
                "Missing Graph credentials. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET."
            )

        data = await _graph_api_request(
            self.session, "POST",
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        self.access_token = data["access_token"]
        self.token_expires = datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600) - 300)
        return self.access_token

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        await self._ensure_token()
        url = f"{GRAPH_API_BASE}{endpoint}" if not endpoint.startswith("http") else endpoint
        return await _graph_api_request(
            self.session, method, url,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            **kwargs,
        )

    async def get_messages(self, folder: str = "inbox", filter_query: Optional[str] = None, top: int = 10):
        params = {"$top": top, "$orderby": "receivedDateTime desc"}
        if filter_query:
            params["$filter"] = filter_query
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        data = await self._request("GET", f"/users/{MAILBOX}/mailFolders/{folder}/messages?{qs}")
        return data.get("value", [])

    async def get_attachments(self, message_id: str):
        data = await self._request("GET", f"/users/{MAILBOX}/messages/{message_id}/attachments")
        return data.get("value", [])

    async def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        await self._ensure_token()
        return await _graph_api_request(
            self.session, "GET",
            f"{GRAPH_API_BASE}/users/{MAILBOX}/messages/{message_id}/attachments/{attachment_id}/$value",
            headers={"Authorization": f"Bearer {self.access_token}"},
            return_bytes=True,
        )

    async def move_message(self, message_id: str, destination_folder: str) -> Dict[str, Any]:
        folder_endpoint = f"/users/{MAILBOX}/mailFolders"
        folders = await self._request("GET", folder_endpoint)
        dest_id = next(
            (f["id"] for f in folders.get("value", [])
             if f["displayName"].lower() == destination_folder.lower()),
            None,
        )
        if not dest_id:
            resp = await self._request("POST", folder_endpoint, json={"displayName": destination_folder})
            dest_id = resp["id"]
        return await self._request(
            "POST", f"/users/{MAILBOX}/messages/{message_id}/move",
            json={"destinationId": dest_id},
        )


# ── Email Poller ──────────────────────────────────────────────────────────────

class EmailPoller:
    """Polls inbox, routes attachments to parser, runs full processing pipeline."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.running = False
        self.processed_ids: set = set()

    # -- watermark ---------------------------------------------------------------

    def _read_watermark(self) -> Optional[datetime]:
        if not os.path.exists(WATERMARK_FILE):
            return None
        try:
            with open(WATERMARK_FILE, "r", encoding="utf-8") as f:
                return datetime.fromisoformat(f.read().strip())
        except Exception as exc:
            self.logger.warning(f"Could not read watermark: {exc}")
            return None

    def _write_watermark(self, dt: datetime) -> None:
        try:
            os.makedirs(os.path.dirname(WATERMARK_FILE), exist_ok=True)
            with open(WATERMARK_FILE, "w", encoding="utf-8") as f:
                f.write(dt.isoformat())
        except Exception as exc:
            self.logger.error(f"Could not write watermark: {exc}")

    # -- poll --------------------------------------------------------------------

    async def poll_once(self, client: GraphClient) -> List[EmailMessage]:
        self.logger.info(f"Polling {MAILBOX} inbox...")

        watermark = self._read_watermark()
        since = (watermark or (datetime.utcnow() - timedelta(hours=24))).isoformat() + "Z"
        self.logger.info(f"  Watermark: {since}")

        messages = await client.get_messages(
            folder=INBOX_FOLDER,
            filter_query=f"receivedDateTime ge {since}",
            top=20,
        )

        po_emails: List[EmailMessage] = []

        for msg in messages:
            msg_id = msg["id"]
            if msg_id in self.processed_ids:
                continue

            from_data    = msg.get("from", {}).get("emailAddress", {})
            sender_email = from_data.get("address", "")
            sender_name  = from_data.get("name", "")
            subject      = msg.get("subject", "")
            body_preview = msg.get("bodyPreview", "")
            received_at  = datetime.fromisoformat(msg.get("receivedDateTime", "").replace("Z", "+00:00"))
            has_att      = msg.get("hasAttachments", False)

            att_names = []
            att_meta_list = []
            if has_att:
                att_meta_list = await client.get_attachments(msg_id)
                att_names = [a.get("name", "") for a in att_meta_list]

            classification = classify_email(sender_email, subject, att_names)

            if classification.source == "direct" and classification.confidence < 0.7:
                self.logger.debug(f"Skipping non-PO email: '{subject}'")
                continue

            # Download all recognised attachments
            attachments: List[EmailAttachment] = []
            for att_meta in att_meta_list:
                if att_meta.get("@odata.type") != "#microsoft.graph.fileAttachment":
                    continue
                att_name     = att_meta.get("name", "")
                content_type = att_meta.get("contentType", "application/octet-stream")
                try:
                    if "contentBytes" in att_meta:
                        content = base64.b64decode(att_meta["contentBytes"])
                    else:
                        content = await client.download_attachment(msg_id, att_meta["id"])
                    attachments.append(EmailAttachment(
                        name=att_name, content_type=content_type,
                        content_bytes=content, size=len(content),
                    ))
                except Exception as exc:
                    self.logger.error(f"  Failed to download '{att_name}': {exc}")

            email_msg = EmailMessage(
                message_id=msg_id, subject=subject,
                sender_email=sender_email, sender_name=sender_name,
                received_at=received_at, body_preview=body_preview,
                has_attachments=has_att, attachments=attachments,
                classification=classification,
            )
            po_emails.append(email_msg)
            self.processed_ids.add(msg_id)
            self.logger.info(
                f"PO email found: '{subject}' | from={sender_email} | "
                f"source={classification.source} | attachments={att_names}"
            )

        self._write_watermark(datetime.utcnow())
        return po_emails

    # -- continuous loop ---------------------------------------------------------

    async def run_continuous(self, callback=None):
        self.running = True
        async with GraphClient() as client:
            while self.running:
                try:
                    emails = await self.poll_once(client)
                    for email in emails:
                        if callback:
                            await callback(email, client)
                        else:
                            await self._default_process(email, client)
                except Exception as exc:
                    self.logger.error(f"Poll cycle error: {exc}", exc_info=True)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    def stop(self):
        self.running = False

    # -- attachment routing ------------------------------------------------------

    async def _default_process(self, email: EmailMessage, client: GraphClient):
        """
        Detect attachment type, log it clearly, route to the correct parser,
        then run the full crosswalk → confidence → CISM → store pipeline.
        """
        self.logger.info(f"Processing: '{email.subject}' | {len(email.attachments)} attachment(s)")

        processed = 0
        for att in email.attachments:
            name_lower = att.name.lower()
            size_kb    = round(att.size / 1024, 1)

            try:
                if name_lower.endswith(".pdf"):
                    self.logger.info(
                        f"  [PDF] {att.name} ({size_kb} KB) — "
                        "sending to Azure Document Intelligence"
                    )
                    await self._route_pdf(att, email)
                    processed += 1

                elif name_lower.endswith((".xml", ".cxml")):
                    self.logger.info(
                        f"  [XML] {att.name} ({size_kb} KB) — "
                        "sending to cXML parser (Ariba/Coupa)"
                    )
                    await self._route_cxml(att, email)
                    processed += 1

                elif name_lower.endswith(".csv"):
                    self.logger.info(
                        f"  [CSV] {att.name} ({size_kb} KB) — "
                        "sending to CSV PO parser"
                    )
                    await self._route_csv(att, email)
                    processed += 1

                else:
                    ext = att.name.rsplit(".", 1)[-1] if "." in att.name else "no-ext"
                    self.logger.info(
                        f"  [SKIP] {att.name} — unsupported type (.{ext})"
                    )

            except Exception as exc:
                self.logger.error(f"  Error processing {att.name}: {exc}", exc_info=True)

        if processed == 0:
            self.logger.warning(
                f"  No processable attachments found in '{email.subject}' — "
                "email will still be moved to Processed-PO"
            )

        try:
            await client.move_message(email.message_id, PROCESSED_FOLDER)
            self.logger.info(f"  Moved to '{PROCESSED_FOLDER}'")
        except Exception as exc:
            self.logger.error(f"  Failed to move message: {exc}")

    # -- parser routes -----------------------------------------------------------

    async def _route_pdf(self, att: EmailAttachment, email: EmailMessage):
        """
        Write PDF to a temp file, call Azure Document Intelligence,
        then run the full _process_po_to_so pipeline.
        """
        from config import get_settings
        import po_parser

        settings = get_settings()

        if not settings.doc_intel_endpoint or not settings.doc_intel_key:
            self.logger.warning(
                f"  Azure Document Intelligence not configured "
                f"(DOC_INTEL_ENDPOINT/DOC_INTEL_KEY missing) — "
                f"saving {att.name} as raw-PDF stub for manual review"
            )
            await self._save_raw_stub(att, email, fmt="pdf")
            return

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(att.content_bytes)
            tmp_path = tmp.name

        try:
            header, lines, raw = po_parser.parse_pdf(
                tmp_path, settings.doc_intel_endpoint, settings.doc_intel_key
            )
            self.logger.info(
                f"  PDF parsed: PO {header.po_no} | {len(lines)} lines | "
                f"ship-to: {header.ship2_name}"
            )
            await self._run_pipeline(header, lines, raw, source="email", fmt="pdf", email=email)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def _route_cxml(self, att: EmailAttachment, email: EmailMessage):
        """Decode cXML bytes and run the full processing pipeline."""
        import po_parser

        text = att.content_bytes.decode("utf-8", errors="replace")

        # Detect source from content
        source = "ariba"
        if "coupa" in text.lower():
            source = "coupa"

        header, lines, raw = po_parser.parse_cxml(text)
        self.logger.info(
            f"  cXML parsed: PO {header.po_no} | {len(lines)} lines | source={source}"
        )
        await self._run_pipeline(header, lines, raw, source=source, fmt="cxml", email=email)

    async def _route_csv(self, att: EmailAttachment, email: EmailMessage):
        """Parse a CSV PO file and run the full processing pipeline."""
        import csv as csvmod
        from io import StringIO
        from models import POHeader, POLineItem

        text = att.content_bytes.decode("utf-8-sig", errors="replace")
        reader = csvmod.DictReader(StringIO(text))
        rows = list(reader)

        if not rows:
            self.logger.warning(f"  CSV {att.name} is empty — skipping")
            return

        first = rows[0]

        def _get(*keys):
            for k in keys:
                v = first.get(k)
                if v:
                    return v
            return ""

        header = POHeader(
            po_no        = _get("po_no", "po_number", "PO Number"),
            order_date   = _get("order_date", "Order Date"),
            ship2_name   = _get("ship2_name", "Ship To Name", "ship_to_name"),
            ship2_add1   = _get("ship2_add1", "Ship To Address"),
            ship2_city   = _get("ship2_city", "Ship To City"),
            ship2_state  = _get("ship2_state", "Ship To State"),
            ship2_zip    = _get("ship2_zip",  "Ship To Zip"),
            ship2_country= _get("ship2_country") or "US",
            supplier_name= _get("supplier_name", "Supplier", "vendor_name"),
            buyer        = _get("buyer", "Buyer"),
            buyer_email  = _get("buyer_email"),
            comments     = _get("comments", "delivery_instructions"),
        )

        lines = []
        for i, row in enumerate(rows, 1):
            def _row(*keys):
                for k in keys:
                    v = row.get(k)
                    if v is not None:
                        return v
                return ""
            lines.append(POLineItem(
                line_no         = int(_row("line_no") or i),
                supplier_part_id= _row("item_id", "supplier_part_id", "Part Number", "customer_part_number"),
                item_description= _row("description", "item_description", "Description"),
                qty_ordered      = float(_row("qty", "qty_ordered", "Quantity") or 0),
                unit_price       = float(_row("unit_price", "price", "Unit Price") or 0),
                unit_of_measure  = _row("uom", "unit_of_measure", "UOM") or "EA",
            ))

        self.logger.info(
            f"  CSV parsed: PO {header.po_no} | {len(lines)} lines | "
            f"ship-to: {header.ship2_name}"
        )
        await self._run_pipeline(header, lines, text, source="email", fmt="csv", email=email)

    # -- shared processing pipeline ----------------------------------------------

    async def _run_pipeline(self, header, lines, raw_content, source: str, fmt: str, email: EmailMessage):
        """
        Run the full crosswalk → confidence → CISM → store pipeline.
        Mirrors server.py's _process_po_to_so() so email-sourced POs get
        the same treatment as uploaded ones.
        """
        from config import get_settings
        from services.processing import local_store
        from services.processing.customer_crosswalk_engine import CustomerCrosswalkEngine
        from services.processing.confidence_scorer import score_customer_po
        from services.processing.duplicate_detector import generate_intake_id, is_duplicate
        from services.processing.cism_so_generator import generate_cism_so
        from services.processing.crosswalk_learner import learn_from_approval
        from models import POPayload, SourceSystem

        settings = get_settings()

        # Dedup check
        intake_id = generate_intake_id(
            header.po_no or email.subject,
            header.ship2_name or email.sender_email,
            source,
        )
        if is_duplicate(intake_id, header.po_no or "", source):
            self.logger.info(f"  Duplicate — skipping PO {header.po_no} (intake_id={intake_id})")
            return

        # Customer + item crosswalk
        engine = CustomerCrosswalkEngine(settings.crosswalk_dir)

        cust_match = engine.match_customer(
            ship2_name   = header.ship2_name or "",
            ship2_add1   = header.ship2_add1 or "",
            ship2_city   = header.ship2_city or "",
            ship2_state  = header.ship2_state or "",
            ship2_zip    = header.ship2_zip or "",
            buyer_email  = header.buyer_email or "",
            source_system= source,
            po_no        = header.po_no or "",
        )
        header.customer_id_p21      = cust_match.p21_customer_id
        header.customer_name_p21    = cust_match.p21_customer_name
        header.customer_match_score = cust_match.match_score
        header.customer_match_method= cust_match.match_method

        cist_detail = engine.get_customer_detail(cust_match.p21_customer_id) if cust_match.p21_customer_id else {}

        item_scores = []
        cism_lines  = []
        for line in lines:
            item_match = engine.match_item(
                supplier_part_id = line.supplier_part_id or "",
                item_description = line.item_description or "",
                unit_price       = line.unit_price or 0.0,
                uom              = line.unit_of_measure or "",
                p21_customer_id  = cust_match.p21_customer_id,
                source_system    = source,
            )
            line.item_id_p21           = item_match.p21_inv_mast_uid or None
            line.crosswalk_match_score = item_match.match_score
            item_scores.append(item_match.match_score)
            cism_lines.append({
                "item_id":           item_match.p21_inv_mast_uid or line.supplier_part_id,
                "qty_ordered":       line.qty_ordered,
                "unit_of_measure":   item_match.unit_of_measure or line.unit_of_measure or "EA",
                "unit_price":        line.unit_price,
                "item_description":  line.item_description or item_match.p21_item_desc,
                "product_group":     item_match.product_group,
                "required_date":     getattr(line, "required_date", "") or getattr(line, "date_due", "") or "",
                "supplier_part_id":  line.supplier_part_id,
                "inv_mast_uid":      item_match.p21_inv_mast_uid,
                "line_no":           line.line_no,
            })

        # Duplicate PO check
        dup = engine.check_duplicate_po(header.po_no or "", cust_match.p21_customer_id)

        # Confidence scoring
        shipto_score = cust_match.shipto_score if cust_match.p21_customer_id else 0.0
        conf = score_customer_po(
            customer_score = cust_match.match_score,
            shipto_score   = shipto_score,
            item_scores    = item_scores,
            is_duplicate   = dup.is_duplicate,
        )

        self.logger.info(
            f"  Pipeline result: PO {header.po_no} | "
            f"customer={cust_match.p21_customer_id} ({cust_match.match_score:.2f}, {cust_match.match_method}) | "
            f"confidence={conf.overall} | lines={len(lines)} | dup={dup.is_duplicate}"
        )

        # CISM SO generation (green/yellow only)
        cism_result = None
        if cust_match.p21_customer_id and conf.overall != "red" and cism_lines:
            try:
                cism_result = generate_cism_so(
                    p21_customer_id    = cust_match.p21_customer_id,
                    p21_customer_name  = cust_match.p21_customer_name,
                    po_no              = header.po_no or "",
                    order_date         = header.order_date or "",
                    requested_date     = getattr(header, "date_due", "") or "",
                    ship2_name         = header.ship2_name or "",
                    ship2_add1         = header.ship2_add1 or "",
                    ship2_add2         = getattr(header, "ship2_add2", "") or "",
                    ship2_city         = header.ship2_city or "",
                    ship2_state        = header.ship2_state or "",
                    ship2_zip          = header.ship2_zip or "",
                    ship2_country      = header.ship2_country or "US",
                    contact_name       = header.buyer or cust_match.p21_customer_name,
                    taker              = settings.p21_default_taker,
                    terms              = cist_detail.get("terms_id", ""),
                    delivery_instructions = header.comments or "",
                    approved           = "Y" if conf.overall == "green" else "N",
                    class_1            = cist_detail.get("class_1id", ""),
                    source_id          = source,
                    lines              = cism_lines,
                    output_dir         = settings.cism_so_output_dir,
                )
            except Exception as exc:
                self.logger.warning(f"  CISM generation failed (non-fatal): {exc}")

        # Auto-learn from green matches
        if conf.overall == "green" and cust_match.p21_customer_id:
            try:
                learn_from_approval(
                    p21_customer_id   = cust_match.p21_customer_id,
                    p21_customer_name = cust_match.p21_customer_name,
                    source_system     = source,
                    ship2_name        = header.ship2_name or "",
                    ship2_add1        = header.ship2_add1 or "",
                    ship2_city        = header.ship2_city or "",
                    ship2_state       = header.ship2_state or "",
                    ship2_zip         = header.ship2_zip or "",
                    po_no             = header.po_no or "",
                    lines             = [
                        {
                            "supplier_part_id": cl["supplier_part_id"],
                            "inv_mast_uid":     cl["inv_mast_uid"],
                            "unit_price":       cl["unit_price"],
                            "unit_of_measure":  cl["unit_of_measure"],
                            "item_description": cl["item_description"],
                            "line_no":          cl["line_no"],
                        }
                        for cl in cism_lines if cl.get("inv_mast_uid")
                    ],
                    crosswalk_dir     = settings.crosswalk_dir,
                )
            except Exception as exc:
                self.logger.warning(f"  Auto-learn failed (non-fatal): {exc}")

        # Save to store
        record = {
            "status":       "processed",
            "po_no":        header.po_no or "",
            "intake_id":    intake_id,
            "source":       source,
            "format":       fmt,
            "confidence":   conf.overall,
            "review_required": conf.review_required,
            "review_status":   "pending",
            "reason":       conf.reason,
            "email_subject":   email.subject,
            "sender":          email.sender_email,
            "received_at":     email.received_at.isoformat(),
            "customer_match": {
                "p21_id":    cust_match.p21_customer_id,
                "name":      cust_match.p21_customer_name,
                "score":     cust_match.match_score,
                "shipto_score": shipto_score,
                "method":    cust_match.match_method,
                "candidates": cust_match.candidates,
            },
            "duplicate": {
                "is_duplicate":    dup.is_duplicate,
                "existing_order":  dup.existing_order_no,
            },
            "lines_count": len(lines),
            "item_scores": [round(s, 2) for s in item_scores],
            "cism":        cism_result,
            "header": {
                "po_no":                header.po_no,
                "ship2_name":           header.ship2_name,
                "ship2_add1":           header.ship2_add1,
                "ship2_city":           header.ship2_city,
                "ship2_state":          header.ship2_state,
                "ship2_zip":            header.ship2_zip,
                "ship2_country":        header.ship2_country,
                "buyer":                header.buyer,
                "buyer_email":          header.buyer_email,
                "comments":             header.comments,
                "order_date":           header.order_date,
                "supplier_name":        header.supplier_name,
                "customer_id_p21":      cust_match.p21_customer_id,
                "customer_name_p21":    cust_match.p21_customer_name,
                "customer_match_score": cust_match.match_score,
                "customer_match_method":cust_match.match_method,
            },
            "lines": [
                {
                    "line_no":              cl["line_no"],
                    "supplier_part_id":     cl["supplier_part_id"],
                    "item_description":     cl["item_description"],
                    "qty_ordered":          cl["qty_ordered"],
                    "unit_price":           cl["unit_price"],
                    "unit_of_measure":      cl["unit_of_measure"],
                    "item_id_p21":          cl["inv_mast_uid"],
                    "product_group":        cl.get("product_group", ""),
                    "crosswalk_match_score":item_scores[i] if i < len(item_scores) else 0,
                }
                for i, cl in enumerate(cism_lines)
            ],
        }
        local_store.save_po(intake_id, record)
        self.logger.info(
            f"  Saved to store: intake_id={intake_id} | confidence={conf.overall} | "
            f"review_required={conf.review_required}"
        )

    async def _save_raw_stub(self, att: EmailAttachment, email: EmailMessage, fmt: str):
        """
        Fallback when a parser dependency (e.g. Doc Intel) is unconfigured.
        Saves a minimal stub so the email appears in the review queue.
        """
        from services.processing import local_store
        from services.processing.duplicate_detector import generate_intake_id

        intake_id = generate_intake_id(att.name, email.sender_email, "email")
        local_store.save_po(intake_id, {
            "status":         "processed",
            "po_no":          att.name,
            "intake_id":      intake_id,
            "source":         "email",
            "format":         fmt,
            "confidence":     "red",
            "review_required": True,
            "review_status":   "pending",
            "reason":         f"Parser not configured — manual review required ({fmt.upper()})",
            "email_subject":  email.subject,
            "sender":         email.sender_email,
            "attachment_name":att.name,
            "lines_count":    0,
            "header":         {"po_no": att.name, "ship2_name": ""},
            "lines":          [],
        })
        self.logger.info(f"  Saved raw stub for {att.name} (intake_id={intake_id})")


# ── CLI test ──────────────────────────────────────────────────────────────────

async def test_poll():
    """Quick smoke-test — requires env vars to be set."""
    logging.basicConfig(level=logging.INFO)
    poller = EmailPoller()
    async with GraphClient() as client:
        emails = await poller.poll_once(client)
        print(f"\nFound {len(emails)} PO emails:\n")
        for e in emails:
            print(f"  Subject:     {e.subject}")
            print(f"  From:        {e.sender_email}")
            print(f"  Source:      {e.classification.source}")
            print(f"  Attachments: {[a.name for a in e.attachments]}")
            print()


if __name__ == "__main__":
    asyncio.run(test_poll())
