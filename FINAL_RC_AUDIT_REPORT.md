# SellMate AI Production-Hardening Audit

**Final iterative report — August 25, 2026**

## Executive conclusion

The repository completed the required **test → independent reproduction → smallest safe fix → regression → targeted retest → integration/stress retest** cycle for the locally testable defects found during this continuation. The final local unittest suite passed **100/100 tests**, all **16 end-to-end simulations passed**, the real malformed-webhook corpus produced **zero 5xx responses**, the real PostgreSQL queue matrix completed **66,400/66,400 jobs exactly once**, the ten-tenant isolation attack suite passed, and the exact PostgreSQL crash/restart inventory test passed.

This is **not a production-ready certification**. Telegram, Groq, S3, Render, and the production database were unavailable for live validation. The distributed rate limiter remains an explicitly reproduced architectural gap: two processes independently allowed 60 requests each, producing **120 combined admissions against a nominal 60-request limit**. A shared Redis or PostgreSQL-backed limiter is still required before claiming cross-process abuse protection.

> **Final disposition:** locally testable critical defects addressed and regression-tested; external integrations and distributed rate limiting remain deployment gates.

## Final result summary

| Area | Result | Evidence |
|---|---:|---|
| Full unittest discovery | **100 passed, 0 failed** | `python3 -m unittest discover -s tests -p 'test*.py'` |
| End-to-end simulation suite | **16 passed, 0 failed** | Each simulation executed independently |
| Real webhook fuzzing | **1,000 cases; 999 HTTP 200, 1 expected HTTP 400, 0 failures** | Real local HTTP server and `/tmp/webhook_fuzz_1000.py` |
| Real queue stress | **66,400 claimed and completed, 0 duplicate claims, 0 pending/active/lost** | 20 configurations: 1/2/5/10 workers × 100/500/1,000/5,000/10,000 jobs |
| Atomic finalization race | **Passed** | 10 duplicate finalizations reduced to one success, one deduction, one audit event |
| Crash/restart atomicity | **Passed at tested boundary** | SIGKILL after the stock-update boundary rolled back stock/order; restart completed once |
| Ten-tenant isolation | **10/10 passed** | Product, variant, inventory, order, dashboard, queue, notification, idempotency, dead-letter paths |
| Live JWT adversarial HTTP | **15 cases passed** | Forged identities, malformed types, `alg=none`, wrong algorithm, oversized token, suspended tenant |
| Live RBAC HTTP | **3/3 passed** | Ordinary denial, valid super-admin access, forged-role denial |
| Migration matrix | **4 passed** | Fresh, repeated, legacy composite-key, duplicate-constraint cases |
| Static/import checks | **55 AST files and 55 imports passed** | 0 syntax failures, 0 import failures |
| Startup/health | **Passed** | `/health` returned HTTP 200 with database connected; all three local workers started |

## Defects independently reproduced and fixed

### Discrete inventory quantities could corrupt order stock

The AI normalizer retained `NaN`, infinity, and fractional quantities. A real PostgreSQL reproduction passed quantity `1.5` through `OrderRepository.finalize_order_with_inventory()`: the order completed and integer stock changed from **5 to 4**, demonstrating unsafe implicit rounding. A separate AI reproduction confirmed that `"NaN"` was retained as a cart quantity.

The fix rejects non-finite, non-positive, fractional, and boolean quantities at the AI normalization and repository mutation boundaries. Transactional finalization, legacy deduction, restoration, and single-stock-update paths now enforce discrete finite quantities before database access. New regressions cover AI normalization, atomic finalization, deduction, restoration, and update helpers. The former decimal-preservation test was documented and updated as an obsolete contract because the schema stores inventory as `INTEGER` and real PostgreSQL reproduced the rounding hazard.

Affected implementation: [`app/services/ai.py`](./app/services/ai.py) and [`app/db/database.py`](./app/db/database.py). Regression coverage: [`tests/test_full_audit_fixes.py`](./tests/test_full_audit_fixes.py) and [`tests/test_batch2_bugs.py`](./tests/test_batch2_bugs.py).

### Weak JWT secrets were accepted at startup

A direct import reproduction with `JWT_SECRET=short` showed that startup accepted a weak key. Configuration now fails fast unless the JWT secret is non-default and at least 32 characters long. A subprocess regression verifies the failure behavior; all later tests used a valid-length isolated QA secret.

Affected implementation: [`app/core/config.py`](./app/core/config.py). Regression coverage: [`tests/test_full_audit_fixes.py`](./tests/test_full_audit_fixes.py).

### Oversized valid JWTs were accepted by protected HTTP endpoints

The live JWT matrix first demonstrated that a valid token with a 5,000-character claim was accepted with HTTP 200. The protected auth dependency now rejects bearer tokens longer than 4,096 characters before JWT decoding or database access. The retest returned HTTP 401 for the oversized token while the valid token remained HTTP 200.

Affected implementation: [`app/api/auth_router.py`](./app/api/auth_router.py). Regression coverage: [`tests/test_full_audit_fixes.py`](./tests/test_full_audit_fixes.py) and `/tmp/jwt_attack_http.py`.

### Public merchant lookup exposed unnecessary merchant data

The unauthenticated `GET /api/auth/merchant/{shop_id}` path returned owner name, phone, and raw merchant requirements. The response now preserves the existing shape for compatibility but returns only public storefront metadata; private fields are empty. A regression verifies that owner name, phone, and raw requirements are redacted while shop name remains available.

Affected implementation: [`app/api/auth_router.py`](./app/api/auth_router.py). Regression coverage: [`tests/test_full_audit_fixes.py`](./tests/test_full_audit_fixes.py).

### Simulation contracts were stale after atomic hardening

Five inherited simulation failures were not production defects. The simulations used string `update_id` values, which the hardened webhook correctly rejects; asserted calls to the removed best-effort `deduct_stock_batch()` path; and expected a retry call without the explicit `can_retry=True` keyword. The fixtures and assertions were updated to represent valid Telegram IDs, atomic finalization, and the current retry contract. All 16 simulations then passed independently.

This was recorded as an obsolete test-contract correction, not a source-code workaround. The changed simulation file is [`tests/simulation_script.py`](./tests/simulation_script.py).

## Previously hardened critical paths revalidated

PostgreSQL transaction tests confirmed that inventory deduction, order metadata, status, timeline, and audit insertion commit atomically. Ten concurrent duplicate finalizations produced one success and one inventory deduction. Duplicate order numbers rolled back the second transaction, and cancellation restored the committed reservation.

A child-process SIGKILL immediately after the actual product stock update left stock unchanged, the order non-completed, and the queue task processing. Worker-health recovery, expired queue lock, expired conversation lock, and a restarted worker then produced one completed order, stock zero, and one completed queue task. This validates the tested crash boundary; it does not validate every possible crash window around external notification delivery.

Signed JWT identity binding was revalidated over live HTTP. Wrong shop, business ID, phone, missing claims, boolean or floating-point business IDs, `alg=none`, wrong signing algorithm, malformed tokens, Unicode shop identity, oversized tokens, and suspended merchant cases returned controlled 401/403 responses. A valid token returned 200.

The 1,000-case malformed webhook corpus included null and scalar bodies, invalid update IDs, malformed messages and callbacks, empty/emoji/oversized text, malformed photos, unsupported media, deep JSON, Unicode, HTML-like text, and duplicate bursts. There were 999 successful acknowledgements, one expected invalid-JSON 400, and no 5xx response or transport exception.

The webhook idempotency race was rerun with 20 concurrent requests for the same update ID and separately for `update_id=0`; both yielded one claim and one queue job. Unknown shops returned 404 without inserting claims. Stale-claim recovery and queue-push failure release paths remain covered by focused regressions.

The queue stress matrix completed every configuration exactly once with zero duplicate claims and no residual pending or active tasks. Throughput ranged approximately from 651 to 2,246 jobs per second in the observed local environment; these are sandbox observations, not production SLOs.

The notification worker leasing path was tested with two workers against one notification row; only one claimant succeeded. Focused tests also cover success, retry, and lease behavior. External Telegram delivery was not live-tested.

## Security, privacy, and isolation results

The ten-tenant PostgreSQL attack suite passed all 10 iterations without cross-tenant reads or mutations across products, variants, inventory, orders, dashboard data, queue jobs, notifications, idempotency rows, and dead-letter records. The live RBAC suite confirmed ordinary-tenant denial, valid super-admin access, and denial of a forged `SUPER_ADMIN` role claim.

The auth service now normalizes nullable legacy owner and phone values, returns generic authentication failures, enforces claim types, binds all identity claims to the database row, and checks merchant status. Public merchant lookup no longer exposes owner data or raw workflow requirements. Customer-supplied Telegram HTML fields remain escaped and outbound messages are capped at the tested 4,096-character limit.

No real production secrets were printed. QA credentials and temporary test tokens were placeholders. The repository remains uncommitted and unpushed; `HEAD` remains `b167c9453efdbcf847ab8c0220f07d205a8c1cdf`.

## Load and capacity observations

A progressive local HTTP run completed at concurrency levels 5, 10, 25, 50, 100, 250, and 500 with all requests returning HTTP 200. Throughput was approximately 756, 1,087, 1,091, 931, 964, 898, and 217 requests per second respectively. Median latency increased from approximately 5 ms at level 5 to 830 ms at level 500, while p95 reached approximately 2,129 ms at level 500. This indicates a local contention knee around the 500-request burst and is not a production capacity promise.

A duplicate burst of 100 requests completed with all HTTP 200 responses. Queue stress was stronger for exactly-once semantics than for user-facing latency because it exercised the PostgreSQL queue repository directly. Production load testing with realistic database sizing, connection-pool tuning, observability, and real provider calls remains outstanding.

## Blocked or unavailable tests

| Risk | Status | Required follow-up |
|---|---|---|
| Distributed rate limiting | **BLOCKED / unresolved** | Reproduced 120 combined admissions from two processes against a nominal 60 limit. Deploy a shared Redis or PostgreSQL limiter and retest concurrent workers. |
| Telegram API delivery, callback acknowledgement, webhook registration | **BLOCKED** | Run live staging tests with a non-production bot, including provider timeouts, retries, duplicate sends, and credential rotation. |
| Groq/Llama extraction quality and provider quotas | **BLOCKED** | Run live provider-contract, quota, malformed-response, and timeout tests in staging. |
| S3 upload/download and object-access policy | **BLOCKED** | Verify private ACLs, signed URLs, upload-size limits, retention, and failure recovery in staging. |
| Production database migration and rollback | **BLOCKED** | Rehearse against a production clone with schema drift, duplicate-data preflight, realistic volume, locks, backups, and rollback. |
| Production ingress, TLS, proxy, Render deployment | **BLOCKED** | Verify proxy request limits, TLS, webhook retry behavior, deployment health, secrets, and rollback in staging. |

A default root-level unittest discovery command initially found zero tests because this repository requires `-s tests -p 'test*.py'`; the corrected repository-specific command ran all 100 tests successfully. This was a discovery-command issue, not a product failure. One live auth attempt also encountered a contaminated QA database sequence after a manual crash-test row; resetting the isolated fixture and sequence made registration pass. This was a test-environment issue.

## Remaining production risks and recommendations

The most important unresolved issue is the distributed limiter. The current process-local implementation cannot enforce a tenant-wide quota across multiple workers or instances. Implement a shared atomic counter with defined windows, fail-closed behavior for abuse-sensitive endpoints, bounded retention, and monitoring.

The authenticated dashboard profile path still returns the merchant’s own bot token. This may be intentional for settings management, but it is a high-value secret exposed to the browser. Review the product policy; prefer write-only configuration, masked display, explicit reveal authorization, rotation, and audit logging if the full token is not required.

The local health endpoint confirms database connectivity and startup, not downstream provider readiness or worker liveness. Production should expose separate liveness/readiness signals, worker heartbeat age, queue depth, provider health, and alert thresholds. Notification and order workers need staging crash-window tests around external send and queue completion.

The tested atomic helper protects inventory, order metadata, status, and audit writes in one PostgreSQL transaction, but external Telegram delivery and queue acknowledgement remain outside that transaction. A durable reservation/finalization state machine or transactional outbox with idempotent recovery is recommended before production promotion.

The new unique indexes correctly reject duplicate legacy SKU/order-number data. Operators must run duplicate reports and remediate rows before startup; safe migration failure is preferable to silently retaining invalid uniqueness state.

## Files changed in the working tree

The current modified-file set includes inherited hardening changes plus the latest continuation changes: `app/api/auth_router.py`, `app/api/dashboard_router.py`, `app/api/webhook.py`, `app/core/config.py`, `app/db/database.py`, `app/db/schema.sql`, `app/main.py`, `app/services/ai.py`, `app/services/auth.py`, `app/services/dashboard_service.py`, `app/services/idempotency_service.py`, `app/services/rate_limiter.py`, `app/services/recovery_validation.py`, `app/services/validation_service.py`, `app/tests/load_test.py`, `app/workers/notification_worker.py`, `app/workers/order_worker.py`, `tests/simulation_script.py`, `tests/test_batch2_bugs.py`, `tests/test_batch5_edge_cases.py`, `tests/test_batch6_readiness.py`, `tests/test_full_audit_fixes.py`, `tests/test_stock_deduction.py`, and `tests/test_webhook_api_handling.py`. `FINAL_RC_AUDIT_REPORT.md` is this revised report.

The latest production-defect fixes are concentrated in configuration, auth, public dashboard responses, numeric validation, inventory repositories, and AI quantity normalization. Test-only changes correct proven obsolete contracts and add permanent regressions; no tests were weakened or deleted.

## Final verification and repository state

The final checks completed with **55 syntax-valid AST files**, **55 successfully imported modules**, clean `git diff --check`, no lingering Uvicorn test servers, and no remaining `__pycache__` directories after cleanup. No commit was created and nothing was pushed, as required.

## References

[1]: [Database repositories and transactional finalization](./app/db/database.py)
[2]: [Order worker](./app/workers/order_worker.py)
[3]: [Telegram webhook boundary](./app/api/webhook.py)
[4]: [Authentication and merchant API](./app/api/auth_router.py)
[5]: [AI normalization and merge logic](./app/services/ai.py)
[6]: [Runtime configuration](./app/core/config.py)
[7]: [Focused hardening regressions](./tests/test_full_audit_fixes.py)
[8]: [End-to-end simulation suite](./tests/simulation_script.py)
[9]: [Rate limiter](./app/services/rate_limiter.py)
