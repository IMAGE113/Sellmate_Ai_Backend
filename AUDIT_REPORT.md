# SellMate Backend Audit Report

## Phase 1: Full Repository Audit - Comprehensive Findings

### 1. Broken Imports & Stale References

*   **`DashboardRepository`** (Fixed): 
    *   **Issue**: Incorrectly imported from `app.db.database` in `app/api/dashboard_router.py`. It is defined in `app/services/dashboard_service.py`.
*   **`ScriptService` Initialization**:
    *   **Issue**: In `app/workflow/orchestrator.py` (line 72), `ScriptService` is initialized with `self.merchant_repo`. However, `ScriptService` expects a `ScriptRepository`.
    *   **Impact**: Runtime error when calling `script_service.get_script()` as it will try to call `get_merchant_script` on `MerchantRepository`, which doesn't exist.

### 2. Schema Mismatches & Missing Tables

The current `app/db/schema.sql` is missing several tables referenced in the code:
*   **`processed_webhooks`**: Referenced in `app/services/idempotency_service.py`.
*   **`merchant_scripts`**: Referenced in `app/services/script_service.py`.
*   **`conversation_locks`**: Referenced in `app/services/lock_manager.py`.
*   **`products`**: Referenced in `app/workers/order_worker.py` and `app/workflow/orchestrator.py`.
*   **`orders`** & **`businesses`**: While mentioned in `schema.sql` via `ALTER` or `INDEX`, their full `CREATE TABLE` statements are missing from the provided `schema.sql`.

### 3. Queue Contract Inconsistency

*   **`app/api/webhook.py`**: Inserts into `task_queue` using columns `business_id, shop_id, chat_id, user_text, request_hash, status`.
*   **`app/services/queue_manager.py`**: Enqueues using `shop_id, queue_name, payload, correlation_id, status`.
*   **`app/db/schema.sql`**: Defines `task_queue` with `shop_id, queue_name, payload, status, retry_count, worker_id, error_message, correlation_id, ...`.
*   **Impact**: Webhook ingestion will fail because it uses an old column structure (`user_text`, `chat_id`, etc.) that isn't in the new schema.

### 4. AI Service Return Type Hazard

*   **Issue**: `AI.extract_data` in `app/services/ai.py` returns a Python `dict` (`{}`) on failure but returns a JSON `string` on success.
*   **Impact**: Callers like `order_worker.py` and `orchestrator.py` use `json.loads(extracted_json)`. If the AI call fails, `json.loads({})` will raise a `TypeError`.

### 5. Missing Dependencies

*   **`PyJWT`**: Used in `app/services/auth.py` but missing from `requirements.txt`.
*   **`alembic`**: Project has `alembic.ini` and migrations folder, but `alembic` is not in `requirements.txt`.

