# Tool Contract — Mapping Suggester

**Document version:** 1.0
**Date:** 2026-04-21
**Status:** Design (not yet implemented)

---

## 1. Tool Identity

| Field | Value |
|---|---|
| `tool_name` | `mapping_suggester` |
| `version` | `v1` |
| `owner` | PO Agent team |
| `mode` | assistive (human-in-loop) — never autonomous |
| `read` | PO record, customer crosswalk, item crosswalk, SO history |
| `write` | suggestion log only — no direct mapping writes |

---

## 2. Input Contract

```json
{
  "intake_id": "string",
  "po_no": "string",
  "source_system": "ariba | coupa | direct",
  "header": {
    "ship2_name": "string",
    "ship2_add1": "string",
    "ship2_city": "string",
    "ship2_state": "string",
    "ship2_zip": "string",
    "buyer": "string",
    "buyer_email": "string"
  },
  "lines": [
    {
      "line_no": "integer",
      "supplier_part_id": "string",
      "item_description": "string",
      "qty_ordered": "number",
      "unit_price": "number",
      "unit_of_measure": "string"
    }
  ],
  "current_mappings": {
    "customer_id_p21": "string | null",
    "lines": [
      {
        "line_no": "integer",
        "item_id_p21": "string | null"
      }
    ]
  }
}
```

---

## 3. Output Contract

```json
{
  "intake_id": "string",
  "decision_required": true,
  "contract_version": "v1",
  "suggestions": {
    "customer_suggestions": [
      {
        "candidate_id": "string",
        "candidate_name": "string",
        "confidence": "float (0.0–1.0)",
        "reason": "string",
        "evidence": "string"
      }
    ],
    "item_suggestions": [
      {
        "line_no": "integer",
        "supplier_part_id": "string",
        "candidates": [
          {
            "candidate_item_id": "string",
            "candidate_description": "string",
            "confidence": "float (0.0–1.0)",
            "reason": "string",
            "evidence": "string"
          }
        ]
      }
    ]
  }
}
```

`decision_required` is always `true`. Any consumer that ignores this field and auto-applies is violating the contract.

---

## 4. Decision Contract

The operator reviews suggestions and submits decisions via:

```json
{
  "intake_id": "string",
  "user_decisions": [
    {
      "decision": "accept | reject",
      "target_type": "customer | item",
      "line_no": "integer | null",
      "selected_id": "string",
      "rationale": "string (optional)"
    }
  ],
  "audit": {
    "user": "string",
    "timestamp": "ISO 8601"
  }
}
```

Decisions are submitted to `POST /api/v1/suggest/mappings/{intake_id}/decide`.

---

## 5. Learning Contract

| Event | Action | Provenance tag |
|---|---|---|
| `accept` | Upsert candidate into crosswalk via `learn_from_approval` path | `manual_accept` |
| `reject` | Write negative signal to suggestion log | `manual_reject` |
| Overwrite guard | If existing mapping has `confidence ≥ 0.85`, require a second explicit confirmation before overwrite | — |

Negative signals are not yet consumed by the matching engine in v1 but are stored for future retraining.

---

## 6. Non-Goals (v1)

- No autonomous auto-apply under any condition.
- No external LLM API calls required — v1 uses crosswalk + fuzzy match heuristics only.
- No real-time model retraining pipeline in this phase.
- No bulk suggestion across all POs — one PO at a time.
