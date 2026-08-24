# SellMate AI — Batch 6 Production Readiness Report

## Executive conclusion

Batch 6 re-audited BUG-01 through BUG-43, verified the prior focused regression suites, performed a deterministic conversation walkthrough, and searched for known dangerous code patterns. The core customer path is **conditionally production-ready** for the audited behavior: malformed input receives recovery, the main state sequence is reachable, confirmation is state-gated, inventory hardening is covered, and outbound Telegram text is bounded.

Three audit findings remain risks rather than silently being declared fixed: scalar overwrite ambiguity (BUG-32), post-timeout continuity (BUG-38), and shop-wide attribute applicability (BUG-39). They require product or persistence design decisions beyond a safe no-refactor hardening patch. The older legacy tests also contain expectations for pre-Batch-4 behavior and should not be used as the sole release gate.

## Verification performed

| Check | Result |
|---|---|
| Python syntax compilation | Passed for all Batch 6-modified modules and tests. |
| Prior focused regression suites | Passed: 35 tests across Batches 1–6, 0 failures. The mocked AI path logs expected invalid-key errors but the tests pass through the safe fallback. |
| Conversation walkthrough | Passed: `ASK_NAME → ASK_PHONE → ASK_ADDRESS → ASK_TOWNSHIP → ASK_PAYMENT_METHOD → ASK_PAYMENT_SCREENSHOT → ORDER_SUMMARY`. |
| Static dangerous-pattern scan | No naive confirmation substring matcher, direct completion-status write, or per-line stock deduction loop remains. The summary price lookup is now normalized and warning-backed. |
| Regression review | Legacy stock/workflow simulations still assert obsolete pre-hardening behavior; this is test drift, not a newly introduced production regression. |

## Bug-by-bug audit

In the table, “Batch 6” identifies files changed during final hardening; “Prior batch” means the existing fix was re-verified without changing that bug’s implementation. “Not Applicable” means the audit item remains a design/product risk that was not safely solvable within this no-refactor hardening pass; it is listed explicitly under remaining risks.

| Bug ID | Status | Root Cause | Files Modified | Regression Risk | Tests Added |
|---|---|---|---|---|---|
| BUG-01 | Already Fixed | Missing name validation allowed empty input. | Prior batch: `validation_service.py`, `order_worker.py`. | Low; field validation remains in worker and AI normalization. | Batch 1 tests. |
| BUG-02 | Already Fixed | Whitespace/garbage names were accepted. | Prior batch: `validation_service.py`. | Low; Unicode name handling must remain covered. | Batch 1 tests. |
| BUG-03 | Not Applicable | Informational finding; no independent runtime defect after name validation. | None in Batch 6. | Low. | Covered by name regression tests. |
| BUG-04 | Already Fixed | Phone input lacked Myanmar-specific validation. | Prior batch: `validation_service.py`, `order_worker.py`. | Low; normalized phone values must remain ASCII/canonical. | Batch 1 tests. |
| BUG-05 | Already Fixed | Invalid phone lengths and alphabetic values were not rejected. | Prior batch: `validation_service.py`. | Low. | Batch 1 tests. |
| BUG-06 | Already Fixed | Empty or unusably short addresses were accepted. | Prior batch: `validation_service.py`, `order_worker.py`. | Low. | Batch 1 tests. |
| BUG-07 | Not Applicable | Informational address edge-case finding; covered by the address validator’s length and meaningful-content checks. | None in Batch 6. | Low. | Batch 1 tests. |
| BUG-08 | Already Fixed | Customer fields were interpolated into Telegram HTML without escaping. | Prior batch: `order_worker.py`, `validation_service.py`. | Medium; any new Telegram HTML interpolation must use the same escape path. | Prior HTML-safety tests. |
| BUG-09 | Already Fixed | Customer/message fields had insufficient length controls. | Prior batch: `validation_service.py`, `order_worker.py`; Batch 6: `telegram.py`. | Low; summary content can still be semantically truncated at the Telegram boundary. | Batch 5 and Batch 6 tests. |
| BUG-10 | Already Fixed | Township was not reliably checked against merchant coverage. | Prior batch: `validation_service.py`, `order_worker.py`. | Medium; absent merchant coverage configuration remains a business-policy dependency. | Batch 1 tests. |
| BUG-11 | Already Fixed | Burmese township/i18n handling was incomplete. | Prior batch: `validation_service.py`, `order_worker.py`. | Medium; legacy Zawgyi text is not converted. | Batch 1 tests. |
| BUG-12 | Already Fixed | Zero quantity was accepted. | Prior batch: `ai.py`. | Low. | Batch 2 tests. |
| BUG-13 | Already Fixed | Decimal quantity handling collapsed or misinterpreted values. | Prior batch: `ai.py`. | Medium; decimal inventory semantics depend on merchant units. | Batch 2 tests. |
| BUG-14 | Already Fixed | Negative quantity handling was unsafe/silent. | Prior batch: `ai.py`, `order_worker.py`. | Low. | Batch 2 tests. |
| BUG-15 | Already Fixed | Item merge keys used only product name. | Prior batch: `ai.py`. | Medium; variant fields not represented by the extractor cannot be recovered. | Batch 2 tests. |
| BUG-16 | Already Fixed | Stock lookup ignored variants. | Prior batch: `database.py`, `order_worker.py`; Batch 4 atomic deduction. | Low to medium; attributes must be present for exact variant resolution. | Batch 4 tests. |
| BUG-17 | Already Fixed | Product matching was case-sensitive/exact. | Prior batch: `database.py`; Batch 6 summary matching. | Low. | Batch 4 and Batch 6 tests. |
| BUG-18 | Already Fixed | Invalid quantity edits were silently ignored. | Prior batch: `ai.py`. | Low; ambiguous natural-language quantities still require AI interpretation. | Batch 2 tests. |
| BUG-19 | Already Fixed | Cancel was evaluated after field-capture trapping. | Prior batch: `flow_manager.py`. | Low. | Batch 2/3 tests. |
| BUG-20 | Already Fixed | Reset/cancel detection required overly exact English phrases. | Prior batch: `flow_manager.py`. | Medium; command matching remains intentionally conservative. | Batch 2/3 tests. |
| BUG-21 | Already Fixed | Menu/summary intents were captured as field answers. | Prior batch: `order_worker.py`, `flow_manager.py`. | Low. | Batch 2 tests. |
| BUG-22 | Already Fixed | Burmese reset/cancel equivalents were absent. | Prior batch: `flow_manager.py`. | Medium; vocabulary coverage is finite. | Batch 2/3 tests. |
| BUG-23 | Already Fixed | Duplicate answers could cross a state boundary. | Prior batch: `order_worker.py`; Batch 5 duplicate guard. | Medium; process-local duplicate suppression is not distributed. | Batch 3/5 tests. |
| BUG-24 | Already Fixed | Greeting comparison did not strip punctuation or Burmese suffixes. | Prior batch: `ai_parser.py`. | Low; Burmese segmentation remains heuristic. | Batch 3 tests. |
| BUG-25 | Already Fixed | “ok” was matched as a substring and could confirm irreversibly. | Prior batch: `ai_parser.py`; Batch 6 state gating. | Low; strict token handling must remain intact. | Batch 2/3/6 tests. |
| BUG-26 | Already Fixed | Photos were always treated as payment screenshots. | Prior batch: `webhook.py`; Batch 5 recovery reply. | Low; prepaid payment method must be stored exactly as expected. | Batch 5 tests. |
| BUG-27 | Already Fixed | Non-progressing conversations had no escalation counter. | Prior batch: `order_worker.py`, `flow_manager.py`. | Medium; counter is stored in extracted data and depends on worker execution. | Batch 3 tests. |
| BUG-28 | Already Fixed | Unsupported Telegram update types were silently dropped. | Prior batch: `webhook.py`; Batch 5 explicit replies. | Low. | Batch 5 tests. |
| BUG-29 | Already Fixed | Completion bypassed `OrderService.update_status()` and its audit trail. | Prior batch: `order_worker.py`. | Medium; completion still depends on valid prior order status. | Prior completion tests. |
| BUG-30 | Already Fixed | Completed orders had no short correction/cancellation window. | Prior batch: `database.py`, `order_service.py`. | Medium; grace-period behavior depends on database timestamps. | Batch 3 tests. |
| BUG-31 | Already Fixed | Summary edits relied on general extraction without revalidation. | Prior batch: `order_worker.py`. | Medium; field edits still do not show a formal before/after confirmation diff. | Batch 3 tests. |
| BUG-32 | Not Applicable | General scalar merge can overwrite a prior value when extraction misclassifies an edit. A safe fix requires explicit edit intent/diff semantics. | None in Batch 6. | High if AI returns a plausible but incorrect scalar. | Existing validation tests do not prove edit provenance. |
| BUG-33 | Already Fixed | AI failures previously became silent no-ops. | Prior batch: `ai_parser.py`; worker state fallback. | Medium; external AI availability remains operational risk. | Batch 3 and full focused suite. |
| BUG-34 | Already Fixed | Item modification matching was exact and could no-op. | Prior batch: `ai.py`. | Medium; fuzzy matching remains intentionally limited to avoid changing the wrong item. | Batch 2 tests. |
| BUG-35 | Already Fixed | Forwarded text was treated as an original customer answer. | Batch 6: `webhook.py`. | Low; Telegram metadata formats may evolve. | Batch 6 tests. |
| BUG-36 | Already Fixed | Callback updates could lack essential fields and bypass normal message validation. | Prior batch: `webhook.py`. | Low; malformed callbacks are rejected, while valid callbacks use the existing synthetic-message path. | Existing webhook tests. |
| BUG-37 | Already Fixed | Invalid field answers had no distinguishable recovery path. | Prior batch: `validation_service.py`, `order_worker.py`; Batch 5 worker guard. | Low; response scripts remain merchant-configurable. | Batch 1/5/6 tests. |
| BUG-38 | Not Applicable | A cancelled stale order is excluded and a new session starts without historical timeout context. Explaining timeout requires a durable previous-order lookup and product decision on session continuity. | None in Batch 6. | Medium; a returning customer may believe they are resuming. | Walkthrough covers fresh-state recovery, not database cleanup timing. |
| BUG-39 | Not Applicable | Shop-wide required attributes can apply to products for which they are inapplicable. This needs product/category metadata, not a safe state-machine-only patch. | None in Batch 6. | Medium to high for mixed catalogs. | State walkthrough covers configured applicable attributes only. |
| BUG-40 | Fixed | Summary price lookup used exact case-sensitive names and silently defaulted to zero. | Batch 6: `order_worker.py`. | Low; unmatched menu items still display zero with a server warning rather than a false silent success. | Batch 6 static review and summary logic coverage. |
| BUG-41 | Fixed | Script formatting errors returned raw templates without logging or safe substitution. | Batch 6: `script_service.py`. | Low; advanced format specifications can still fall back with a warning. | Batch 6 tests. |
| BUG-42 | Fixed | Cart had no line-count ceiling. | Batch 6: `ai.py`. | Low; the ceiling is per normalized extraction and does not define merchant-specific limits. | Batch 6 tests. |
| BUG-43 | Fixed | Greeting and confirmation fast paths were not state-aware. | Prior batch: `ai_parser.py`; Batch 6 greeting gate. | Low. | Batch 6 tests and walkthrough. |

## Files modified in Batch 6

| File | Purpose |
|---|---|
| `app/api/webhook.py` | Recovery for forwarded, empty, emoji-only, oversized, duplicate, spam, unsupported, edited, and COD-photo updates. |
| `app/workers/order_worker.py` | Direct queue-payload recovery and normalized summary price matching. |
| `app/services/ai_parser.py` | State-gated greeting fast path. |
| `app/services/ai.py` | Cart-line ceiling. |
| `app/services/script_service.py` | Safe placeholder substitution and warning logging. |
| `app/services/telegram.py` | Outbound Telegram length cap. |
| `tests/test_batch6_readiness.py` | Final-hardening regression and walkthrough tests. |

## Remaining risks and release recommendations

The remaining material risks are BUG-32, BUG-38, and BUG-39. They should be scheduled as explicit product/design work rather than patched through increasingly broad heuristics. Before a high-volume launch, move duplicate/spam tracking to shared storage, add a real end-to-end database test for the five-minute completed-order grace period, and refresh legacy tests that still assert pre-Batch-4 per-item stock calls and obsolete status transitions.

## Commit

**Batch 6 commit:** `3a4d76b404306e926e655a3505b6d15093eef96e`
