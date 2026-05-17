"""
mapping_suggester.py — Mapping Suggestion Agent (BACKLOG_NEXT.md P1 #8).

Returns ranked customer and item mapping suggestions for a PO using
crosswalk + fuzzy heuristics only (no LLM calls).
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

from services.processing.address_normalizer import (
    composite_address_score,
    name_similarity,
    normalize_name,
    normalize_zip,
)
from services.processing.customer_crosswalk_engine import CustomerCrosswalkEngine

logger = logging.getLogger(__name__)

SUGGESTION_LOG_DIR = os.environ.get("SUGGESTION_LOG_DIR", "/app/data/suggestion_log")


def _ensure_suggestion_dir():
    os.makedirs(SUGGESTION_LOG_DIR, exist_ok=True)


async def suggest_mappings(
    po_data: dict,
    customer_engine: CustomerCrosswalkEngine,
    item_crosswalk_df=None,
) -> dict:
    """
    Returns ranked customer and item mapping suggestions for a PO.
    Uses crosswalk + fuzzy heuristics only (no LLM calls).
    """
    header = po_data.get("header", {})
    lines = po_data.get("lines", [])
    source = po_data.get("source", "")
    po_no = header.get("po_no", "")

    ship2_name = header.get("ship2_name", "")
    ship2_add1 = header.get("ship2_add1", "")
    ship2_city = header.get("ship2_city", "")
    ship2_state = header.get("ship2_state", "")
    ship2_zip = header.get("ship2_zip", "")
    buyer_email = header.get("buyer_email", "")
    source_customer_id = header.get("source_customer_id", "")

    current_customer_id = (
        header.get("customer_id_p21")
        or po_data.get("customer_match", {}).get("p21_id", "")
    )
    current_customer_score = (
        header.get("customer_match_score")
        or po_data.get("customer_match", {}).get("score", 0)
        or 0
    )

    # ── Customer suggestions ──────────────────────────────────────────
    customer_suggestions = []
    seen_cids = set()

    # Stage 1: learned exact match (source_system + source_customer_id)
    if source and source_customer_id:
        for row in customer_engine.customer_xw:
            if (
                row.get("source_system", "") == source
                and row.get("source_customer_id", "") == source_customer_id
            ):
                cid = row["p21_customer_id"]
                seen_cids.add(cid)
                customer_suggestions.append(
                    {
                        "candidate_id": cid,
                        "candidate_name": row.get("p21_customer_name", ""),
                        "confidence": 1.0,
                        "reason": "learned",
                        "evidence": (
                            f"learned mapping: source={source}, "
                            f"source_customer_id={source_customer_id}"
                        ),
                    }
                )
                break

    # Stage 2: exact_name_zip
    name_norm = normalize_name(ship2_name)
    zip5 = normalize_zip(ship2_zip)
    if name_norm and zip5:
        for row in customer_engine.customer_xw:
            if (
                row.get("ship2_name_normalized", "") == name_norm
                and row.get("ship2_zip", "") == zip5
            ):
                cid = row["p21_customer_id"]
                if cid not in seen_cids:
                    seen_cids.add(cid)
                    customer_suggestions.append(
                        {
                            "candidate_id": cid,
                            "candidate_name": row.get("p21_customer_name", ""),
                            "confidence": 0.95,
                            "reason": "exact_name_zip",
                            "evidence": (
                                f"name+zip exact match: '{ship2_name}' → "
                                f"'{row.get('p21_customer_name', '')}' at zip {zip5}"
                            ),
                        }
                    )
                break

    # Stage 3: fuzzy address match
    fuzzy_candidates = []
    for row in customer_engine.customer_xw:
        score = composite_address_score(
            ship2_name,
            ship2_add1,
            ship2_city,
            ship2_state,
            ship2_zip,
            row.get("ship2_name", ""),
            row.get("ship2_add1", ""),
            row.get("ship2_city", ""),
            row.get("ship2_state", ""),
            row.get("ship2_zip", ""),
        )
        if score >= 0.50:
            fuzzy_candidates.append((score, row))

    fuzzy_candidates.sort(key=lambda x: x[0], reverse=True)

    for score, row in fuzzy_candidates[:3]:
        cid = row["p21_customer_id"]
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        conf = round(score, 4) if score >= 0.65 else round(score * 0.9, 4)
        reason = "fuzzy" if score >= 0.65 else "fuzzy_weak"
        customer_suggestions.append(
            {
                "candidate_id": cid,
                "candidate_name": row.get("p21_customer_name", ""),
                "confidence": conf,
                "reason": reason,
                "evidence": (
                    f"name fuzzy match: '{ship2_name}' → "
                    f"'{row.get('p21_customer_name', '')}' at {score:.2f}"
                ),
            }
        )

    # Stage 4: PO pattern match
    if po_no and po_no in customer_engine.po_history:
        po_records = customer_engine.po_history[po_no]
        cid_counts = defaultdict(int)
        for r in po_records:
            cid_counts[r.get("p21_customer_id", "")] += 1
        best_cid = max(cid_counts, key=cid_counts.get) if cid_counts else ""
        if best_cid and best_cid not in seen_cids:
            seen_cids.add(best_cid)
            cust = customer_engine.customers_p21.get(best_cid, {})
            po_shipto = fuzzy_candidates[0][0] if fuzzy_candidates else 0.50
            conf = 0.85
            reason = "po_pattern"
            for score, row in fuzzy_candidates:
                if (
                    row.get("p21_customer_id", "") == best_cid
                    and score > 0.85
                ):
                    conf = round(score, 4)
                    reason = "fuzzy+po_confirm"
                    break
            customer_suggestions.append(
                {
                    "candidate_id": best_cid,
                    "candidate_name": cust.get("customer_name", ""),
                    "confidence": conf,
                    "reason": reason,
                    "evidence": (
                        f"PO pattern match: PO#{po_no} historically belongs "
                        f"to customer {best_cid}"
                    ),
                }
            )

    # Limit to 3
    customer_suggestions = customer_suggestions[:3]

    # ── Item suggestions ──────────────────────────────────────────────
    item_suggestions = []

    for line in lines:
        line_no = line.get("line_no", 0)
        supplier_part_id = line.get("supplier_part_id", "")
        item_description = line.get("item_description", "")
        unit_price = line.get("unit_price", 0)
        uom = line.get("unit_of_measure", "")
        current_item_id = line.get("item_id_p21", "")
        current_item_score = line.get("crosswalk_match_score", 0) or 0

        # Only suggest if blank or low confidence
        has_good_match = bool(current_item_id) and current_item_score >= 0.85
        if has_good_match:
            continue

        candidates = []
        seen_item_ids = set()
        part = supplier_part_id.strip() if supplier_part_id else ""

        # Step 1: Customer-specific part number lookup
        if current_customer_id and current_customer_id in customer_engine.customer_items and part:
            for row in customer_engine.customer_items[current_customer_id]:
                if row.get("customer_part_number", "").strip() == part:
                    uid = row.get("p21_inv_mast_uid", "")
                    if uid and uid not in seen_item_ids:
                        seen_item_ids.add(uid)
                        candidates.append(
                            {
                                "candidate_item_id": uid,
                                "candidate_description": row.get("p21_item_desc", ""),
                                "confidence": 1.0,
                                "reason": "customer_part",
                                "evidence": (
                                    f"exact customer part match: '{part}' → "
                                    f"inv_mast_uid {uid}"
                                ),
                            }
                        )

        # Step 2: Global part number lookup
        if part in customer_engine.global_items:
            rows = customer_engine.global_items[part]
            for r in rows[:3]:
                uid = r.get("p21_inv_mast_uid", "")
                if uid and uid not in seen_item_ids:
                    seen_item_ids.add(uid)
                    candidates.append(
                        {
                            "candidate_item_id": uid,
                            "candidate_description": r.get("p21_item_desc", ""),
                            "confidence": 0.90,
                            "reason": "global_part",
                            "evidence": (
                                f"global part match: '{part}' → inv_mast_uid {uid}"
                            ),
                        }
                    )

        # Step 3: Direct item_id match against item master
        if part and len(candidates) < 3:
            part_norm = normalize_name(part)
            for uid, item in customer_engine.item_master.items():
                desc_norm = item.get("p21_item_desc_normalized", "")
                if part_norm and part_norm == desc_norm:
                    if uid not in seen_item_ids:
                        seen_item_ids.add(uid)
                        candidates.append(
                            {
                                "candidate_item_id": uid,
                                "candidate_description": item.get("p21_item_desc", ""),
                                "confidence": 0.95,
                                "reason": "direct_item",
                                "evidence": (
                                    f"direct item match: '{part}' → "
                                    f"{item.get('p21_item_desc', '')}"
                                ),
                            }
                        )
                        if len(candidates) >= 3:
                            break

        # Step 4: Fuzzy description match
        if item_description and len(candidates) < 3:
            desc_norm = normalize_name(item_description)
            best_score = 0.0
            best_item = None
            best_uid = ""
            for uid, item in customer_engine.item_master.items():
                item_desc_norm = item.get("p21_item_desc_normalized", "")
                if not item_desc_norm:
                    continue
                score = name_similarity(desc_norm, item_desc_norm)
                if score > best_score:
                    best_score = score
                    best_item = item
                    best_uid = uid

            if best_item and best_score >= 0.60 and best_uid not in seen_item_ids:
                candidates.append(
                    {
                        "candidate_item_id": best_uid,
                        "candidate_description": best_item.get("p21_item_desc", ""),
                        "confidence": round(best_score * 0.80, 4),
                        "reason": "fuzzy_desc",
                        "evidence": (
                            f"fuzzy description match: '{item_description}' → "
                            f"'{best_item.get('p21_item_desc', '')}' at {best_score:.2f}"
                        ),
                    }
                )

        if candidates:
            item_suggestions.append(
                {
                    "line_no": line_no,
                    "supplier_part_id": supplier_part_id,
                    "candidates": candidates[:3],
                }
            )

    # ── Overwrite guard ───────────────────────────────────────────────
    overwrite_guard = False
    current_confidence = None

    if current_customer_id and current_customer_score >= 0.85:
        overwrite_guard = True
        current_confidence = current_customer_score

    for line in lines:
        item_score = line.get("crosswalk_match_score", 0) or 0
        if line.get("item_id_p21") and item_score >= 0.85:
            overwrite_guard = True
            if current_confidence is None:
                current_confidence = item_score
            else:
                current_confidence = max(current_confidence, item_score)

    return {
        "intake_id": po_data.get("intake_id", ""),
        "decision_required": True,
        "contract_version": "v1",
        "overwrite_guard": overwrite_guard,
        "current_confidence": round(current_confidence, 2)
        if current_confidence is not None
        else None,
        "suggestions": {
            "customer_suggestions": customer_suggestions,
            "item_suggestions": item_suggestions,
        },
    }


def write_rejection_log(intake_id: str, decisions: list) -> str:
    """Write rejected decisions to suggestion log."""
    _ensure_suggestion_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SUGGESTION_LOG_DIR, f"{intake_id}_{ts}.json")
    with open(path, "w") as f:
        json.dump(
            {
                "intake_id": intake_id,
                "timestamp": datetime.utcnow().isoformat(),
                "rejected_decisions": decisions,
            },
            f,
            indent=2,
            default=str,
        )
    logger.info(f"Suggestion rejection logged: {path}")
    return path
