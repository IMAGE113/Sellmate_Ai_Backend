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


## Phase 3: Data Consistency Audit

This section details inconsistencies found across the Order model, extracted data, merchant settings, and workflow logic.

### 1. Workflow State vs. Order Status Mismatch

There is a significant disconnect between the workflow states managed by `FlowManager` (derived from `extracted_data`) and the formal `status` field in the `orders` table, which is managed by `OrderService`.

*   **`FlowManager` States (from `app/workflow/flow_manager.py` and `app/core/scripts.py`):**
    *   `ASK_ITEMS`
    *   `ASK_NAME`
    *   `ASK_PHONE`
    *   `ASK_ADDRESS`
    *   `ASK_TOWNSHIP`
    *   `ASK_SIZE`
    *   `ASK_COLOR`
    *   `ASK_PAYMENT_METHOD`
    *   `ASK_PAYMENT_SCREENSHOT`
    *   `ORDER_CONFIRMED` (after fix)
    *   `HUMAN_TAKEOVER`
    *   `MENU_INFO`
    *   `GREETING`

*   **`OrderService` Statuses (from `app/services/order_service.py` and `app/db/schema.sql`):**
    *   `NEW_CHAT`
    *   `COLLECTING_INFO`
    *   `WAITING_PAYMENT`
    *   `PAYMENT_PENDING_REVIEW`
    *   `PAYMENT_CONFIRMED`
    *   `READY_TO_SHIP`
    *   `COMPLETED`
    *   `CANCELLED`

**Inconsistency:** The `FlowManager` determines the bot's next response based on the `extracted_data` and its internal logic, returning a `status_key` that directly maps to a script. However, this `status_key` is not used to update the `orders.status` field. The `orders.status` is updated separately by `OrderService` based on its own `VALID_TRANSITIONS` state machine. This means the formal order status in the database might not accurately reflect the current conversational state of the bot, leading to potential discrepancies in reporting, analytics, and external integrations that rely on `orders.status`.

**Root Cause:** Two separate state management mechanisms are at play without clear synchronization or mapping between them. The `FlowManager` drives the conversational flow, while `OrderService` manages the persistent lifecycle status of an order.

**Exact Fix Recommendation:**
1.  **Establish a clear mapping:** Define a comprehensive mapping between `FlowManager`'s `status_key` values and `OrderService`'s `orders.status` values.
2.  **Synchronize updates:** Modify `orchestrator.py` and `order_worker.py` to call `OrderService.update_status` with the appropriate mapped status whenever `FlowManager.get_next_step` determines a new conversational state that corresponds to a change in the persistent order status.

### 2. Payment Screenshot Handling Deficiency

Prepaid payment flows requiring a screenshot are currently broken due to a lack of processing in the webhook.

*   **`app/api/webhook.py` (lines 60-68):** When a message contains a `photo`, the webhook merely logs an audit event (`Photo uploaded via Telegram`) and returns `{"ok": True}`. It does not:
    *   Attach the image to the order.
    *   Update any `order_data` fields (e.g., `payment_screenshot_received`).
    *   Queue any further processing for the screenshot.

**Inconsistency:** The `FlowManager` (in `app/workflow/flow_manager.py`, lines 47-50) correctly checks for `payment_screenshot_received` when `payment_method` is "Prepaid" to determine if it should `ASK_PAYMENT_SCREENSHOT`. However, because the webhook never updates this field, the bot will continuously ask for the screenshot, even if the user has uploaded it.

**Root Cause:** The webhook endpoint, which is the entry point for Telegram messages, does not integrate photo uploads into the order processing workflow. It treats photo uploads as a terminal event rather than a state-changing input.

**Exact Fix Recommendation:**
1.  **Process photo uploads:** Modify `app/api/webhook.py` to handle photo messages. This would involve:
    *   Downloading the photo from Telegram (using the `tg_bot_token`).
    *   Storing the photo (e.g., in S3, and saving the URL to the `orders.extracted_data` JSONB field or a new dedicated `payment_screenshot_url` field in the `orders` table).
    *   Updating the `payment_screenshot_received` flag within the `extracted_data` for the relevant order.
    *   Queueing the order for further processing (e.g., via `inbound_messages` queue) to allow `FlowManager` to re-evaluate the state and transition to `PAYMENT_RECEIVED_WAITING_REVIEW` or `ORDER_CONFIRMED`.

### 3. Merchant Settings Configuration Gap

Critical workflow-controlling settings are not exposed or managed through the merchant dashboard.

*   **`FlowManager` (e.g., `app/workflow/flow_manager.py`):** Relies on `self.settings.get("setting_require_name")`, `self.settings.get("setting_require_phone")`, `self.settings.get("setting_require_address")`, `self.settings.get("setting_require_size")`, `self.settings.get("setting_require_color")`, and `self.settings.get("setting_require_payment_screenshot")`.

*   **`dashboard_service.py` (lines 81-113):** The `update_merchant_settings` function primarily updates `tg_bot_token` and calls `setWebhook`. It does not provide mechanisms to configure the `setting_require_*` flags that control the workflow.

**Inconsistency:** Merchants cannot customize essential aspects of their bot's information collection flow through the dashboard. This leads to a rigid workflow that might not suit all businesses or could be misconfigured if these settings are only managed directly in the database.

**Root Cause:** The dashboard's settings management functionality is incomplete and does not cover all configurable workflow parameters used by the `FlowManager`.

**Exact Fix Recommendation:**
1.  **Extend Dashboard Service:** Modify `app/services/dashboard_service.py` to include endpoints and logic for updating all `setting_require_*` flags within the `businesses.workflow_config` JSONB field.
2.  **Update UI:** (Requires frontend work) The merchant dashboard UI needs to be updated to expose these settings to merchants.

### 4. Case Sensitivity and Naming Mismatches for Payment Method

The system needs to be robust against variations in payment method naming.

*   **`ai.py` (line 34):** Specifies `payment_method: 'COD' or 'Prepaid'` in the system prompt for AI extraction.
*   **`flow_manager.py` (line 47):** Checks `self.order_data.get("payment_method") == "Prepaid"`.
*   **`schema.sql` (orders.extracted_data JSONB):** Stores `payment_method` as part of the JSONB, which is case-sensitive for key lookups.

**Inconsistency:** While the AI prompt guides towards 'COD' or 'Prepaid', there's no explicit normalization or case-insensitive matching for `payment_method` values once extracted. If the AI (or a user input) provides `cod`, `cashondelivery`, `PaymentMethod`, etc., these might not be correctly recognized by `FlowManager` or other services expecting exact matches.

**Root Cause:** Lack of explicit normalization and case-insensitive handling for the `payment_method` field across different components.

**Exact Fix Recommendation:**
1.  **Normalization in AI Extraction/Merging:** In `ai.py`, within the `extract_data` or `merge_data` function, normalize the `payment_method` to a canonical form (e.g., `COD` or `PREPAID`) before storing it in `extracted_data`.
2.  **Case-Insensitive Comparison:** In `flow_manager.py` and any other service consuming `payment_method`, ensure comparisons are case-insensitive (e.g., `self.order_data.get("payment_method", "").lower() == "prepaid".lower()`).
3.  **Update AI Prompt:** Potentially refine the AI prompt in `ai.py` to explicitly instruct the AI to return `COD` or `PREPAID` to reduce variations at the source.

## Phase 4: Production Failure Analysis

This section analyzes potential production failure risks and scalability concerns, assuming a scenario with 10,000 merchants and 100,000 conversations.

### 1. Race Conditions and Conversation Overwrite Risks

**Analysis:** The system employs a `LockManager` in `order_worker.py` to acquire a conversation lock per `chat_id`. This mechanism is crucial for preventing multiple concurrent processes from modifying the same conversation state, effectively mitigating race conditions and conversation overwrite risks for individual chats. Messages for the same `chat_id` arriving rapidly will be queued, and the `LockManager` ensures sequential processing. If a lock cannot be acquired, the task is re-queued with `can_retry=True`, indicating a robust retry mechanism.

**Probability:** LOW
**Impact:** LOW (due to `LockManager` and retry mechanism)
**Fix Recommendation:** The current implementation appears robust. Continue to monitor lock acquisition metrics in production.

### 2. Async Issues

**Analysis:** The codebase consistently utilizes `asyncio` and `httpx.AsyncClient` for asynchronous operations, with proper use of the `await` keyword. This indicates a well-structured approach to handling concurrent I/O operations, which is essential for a scalable backend.

**Probability:** LOW
**Impact:** LOW
**Fix Recommendation:** Continue to follow best practices for asynchronous programming. Implement comprehensive unit and integration tests for async flows.

### 3. State Corruption Risks

**Analysis:**
*   **`orders.extracted_data`:** The `extracted_data` field, stored as JSONB, is merged using `ai.merge_data`. The `force_dict` utility in `order_worker.py` helps prevent malformed AI responses from causing immediate `TypeError` exceptions by ensuring the data is always a dictionary. However, if the AI consistently returns semantically incorrect but syntactically valid JSON, it could lead to logical state corruption within `extracted_data` that `FlowManager` relies on.
*   **`orders.status` vs. `FlowManager` `status_key`:** As identified in Phase 3, the `orders.status` (managed by `OrderService` with `VALID_TRANSITIONS`) and `FlowManager`'s `status_key` are not synchronized. This architectural mismatch can lead to a perceived state corruption from the bot's conversational perspective, where the bot's responses (`status_key`) do not align with the formal order status in the database (`orders.status`). This can cause confusion for external systems or analytics relying on `orders.status`.

**Probability:** MEDIUM
**Impact:** MEDIUM
**Fix Recommendation:**
1.  **AI Response Validation:** Implement stricter schema validation for AI-extracted data to catch semantically incorrect data before merging. Consider using Pydantic models for `extracted_data`.
2.  **State Synchronization:** Implement the fix recommendations from Phase 3 to synchronize `FlowManager`'s `status_key` with `OrderService`'s `orders.status` to ensure a consistent view of the order state across all components.

### 4. Duplicate Message Risks

**Analysis:** The `webhook.py` endpoint incorporates an `IdempotencyService` that uses `update_id` from Telegram to prevent duplicate processing of the same incoming message. This is a critical and effective mechanism for ensuring that each Telegram update is processed exactly once, even if Telegram sends it multiple times.

**Probability:** LOW
**Impact:** LOW
**Fix Recommendation:** The current idempotency implementation is sound. Ensure proper monitoring of the `processed_webhooks` table for any anomalies.

### 5. Webhook Retry Problems

**Analysis:** The `webhook.py` endpoint returns `{"ok": True}` in its `except` block (line 94), even when an exception occurs during processing. This behavior signals to Telegram that the webhook call was successful, preventing Telegram from retrying the message. If an error occurs *after* the idempotency check but *before* the message is successfully pushed to the `inbound_messages` queue, the message will be silently lost without any retry from Telegram.

**Probability:** MEDIUM
**Impact:** HIGH (potential for lost messages and customer interactions)
**Fix Recommendation:** Modify `webhook.py` to return an HTTP 500 status code (or any non-2xx status) if an error occurs during the critical path (e.g., queuing the message). This will instruct Telegram to retry the webhook delivery, preventing message loss. Implement robust error logging and alerting for webhook failures.

### 6. Telegram Delivery Failures

**Analysis:** The `order_worker.py` is responsible for sending replies via Telegram. If Telegram's API is unavailable or experiences issues, the `send` function call will fail. The current `try-except` block in `run_worker` will catch this exception, and the task will be marked as failed. If the task is configured to be retriable (`can_retry=True`), it will be re-queued for later processing. This provides a basic level of resilience.

**Probability:** MEDIUM (external dependency)
**Impact:** MEDIUM (delayed or failed customer communication)
**Fix Recommendation:**
1.  **Exponential Backoff and Retry:** Ensure the queue manager implements an exponential backoff strategy for retrying failed tasks to avoid overwhelming the Telegram API during outages.
2.  **Dead Letter Queue:** Implement a dead-letter queue for tasks that repeatedly fail after several retries. This allows for manual inspection and recovery of messages that cannot be delivered automatically.
3.  **Monitoring and Alerting:** Set up comprehensive monitoring for Telegram API response times and error rates, with alerts for sustained issues.

### 7. Scalability Concerns

**Analysis:**
*   **Database Contention:** With 100,000 conversations, frequent updates to the `orders` table (especially the `extracted_data` JSONB field and `timeline` array) could lead to database write contention. The `get_or_create_active_order` and `update_order_status` operations are critical paths.
*   **Queue Throughput:** The `inbound_messages` queue is central. While `asyncpg` and `QueueManager` are designed for high throughput, the rate of message ingestion and processing needs to be carefully monitored. A sudden surge in messages could overwhelm the workers or the database.
*   **AI API Latency/Rate Limits:** The `ai.extract_data` call is an external API dependency. With 100,000 conversations, the volume of AI calls will be substantial. Latency from the AI provider or hitting rate limits could become a bottleneck. The `rate_limiter` service is a good start, but its configuration and effectiveness need to be validated at scale.
*   **Lock Manager Performance:** The `LockManager` relies on database operations (`acquire` and `release`). At high concurrency, these operations could become a bottleneck if not optimized.

**Probability:** HIGH (as scale increases)
**Impact:** HIGH (system slowdowns, unresponsiveness, message backlogs)
**Fix Recommendation:**
1.  **Database Optimization:** Review database indexing, consider partitioning for `orders` and `audit_logs` tables, and optimize queries. Monitor database performance metrics (CPU, I/O, connection pool usage).
2.  **Horizontal Scaling:** Ensure the `order_worker` can be horizontally scaled by deploying multiple instances. The `QueueManager` and `LockManager` should support this.
3.  **AI API Management:** Implement robust circuit breakers and fallback mechanisms for the AI API. Explore caching strategies for common AI responses. Negotiate higher rate limits with the AI provider or consider alternative AI models/providers.
4.  **Load Testing:** Conduct extensive load testing to identify bottlenecks and validate the system's performance under anticipated production loads.
5.  **Monitoring:** Implement comprehensive monitoring for queue depths, worker health, AI API usage, and database performance. Set up alerts for thresholds indicating potential scalability issues.

## Phase 5: Codebase Health Audit

This section reviews the entire architecture and scores each area out of 10, based on the codebase exploration and existing documentation.

| Area | Score | Justification |
| :--- | :--- | :--- |
| 1. Database Design | 8/10 | Solid relational schema with JSONB for flexibility. Missing foreign key constraints in some areas and the `orders.status` vs `FlowManager` mismatch slightly reduce the score. |
| 2. Multi-Tenant Isolation | 9/10 | Strong emphasis on `shop_id` filtering across repositories and services. The architecture is fundamentally designed for multi-tenancy. |
| 3. Workflow Engine | 6/10 | The `FlowManager` is functional but tightly coupled to `extracted_data` and disconnected from the formal `orders.status`. It lacks a robust, unified state machine. |
| 4. AI Integration | 7/10 | Good use of system prompts and JSON extraction. However, reliance on a single provider (Groq) without implemented failovers (though planned) and potential for semantic data corruption lower the score. |
| 5. Error Handling | 7/10 | Basic `try-except` blocks are present, but the webhook swallowing errors (returning `{"ok": True}`) is a significant flaw. Needs more structured, centralized error management. |
| 6. Logging | 8/10 | Good use of `logging` module and a dedicated `audit_logs` table for business events. Could benefit from more structured logging (e.g., JSON logs) for easier parsing. |
| 7. Security | 7/10 | Basic security measures are in place (JWT, token storage). However, the lack of input sanitization for `payment_method` and potential vulnerabilities in webhook handling need addressing. |
| 8. Scalability | 8/10 | Async architecture, connection pooling, and queue-based worker design provide a strong foundation for scaling. Database contention and queue throughput will be the primary bottlenecks. |
| 9. Maintainability | 7/10 | Code is reasonably organized into services, but some files (like `order_worker.py`) are becoming large and complex. The disconnect between workflow and order status makes it harder to reason about the system. |
| 10. SaaS Readiness | 8/10 | The core features for a multi-tenant SaaS are present (isolation, custom scripts, dashboard API). Fixing the identified bugs and inconsistencies will make it fully ready. |

**Overall Architecture Score: 75/100**

## Phase 6: Beta Launch Readiness

Assuming 10 beta merchants, 100 daily customers, and real orders, this section assesses the backend's readiness.

**Can this backend survive?** Yes, but with significant manual intervention required due to the broken prepaid payment flow and state inconsistencies.

### Critical Blockers (Must fix before beta)
1.  **Prepaid Payment Flow:** The webhook must process photo uploads and update the order state to allow the workflow to proceed past `ASK_PAYMENT_SCREENSHOT`.
2.  **Webhook Error Swallowing:** The webhook must return non-200 status codes on failure to ensure Telegram retries message delivery.

### Major Blockers (Should fix before beta)
1.  **State Synchronization:** Align `FlowManager`'s `status_key` with `OrderService`'s `orders.status` to ensure accurate reporting and dashboard data.
2.  **Merchant Settings UI/API:** Ensure merchants can actually configure the `setting_require_*` flags that control the bot's behavior.

### Minor Blockers (Can fix during beta)
1.  **Payment Method Normalization:** Implement case-insensitive handling and normalization for `payment_method` to improve robustness.
2.  **AI Fallback/Failover:** Implement the planned multi-provider failover for the AI extraction service to improve reliability.

## Phase 7: Hidden Bug Hunt

This section identifies potential future bugs and risks that have not yet manifested but could cause issues in production.

### 1. Future Payment Bugs

*   **Partial Payments:** The system currently assumes a binary payment state (paid or not paid). If a customer makes a partial payment, the workflow has no mechanism to handle it, potentially leading to stalled orders or incorrect confirmations.
*   **Currency/Amount Mismatches:** The `payment_reviews` table stores the `screenshot_url` but doesn't explicitly verify the transferred amount against the `orders.total_price`. A malicious user could upload a screenshot of a smaller payment, and if the admin isn't careful, the order might be confirmed incorrectly.

### 2. Future Workflow Bugs

*   **Infinite Loops:** If the AI consistently fails to extract a required field (e.g., due to a misunderstanding of the user's dialect), the `FlowManager` will repeatedly ask for the same information, creating an infinite loop. A retry counter or fallback to human takeover after $N$ failed attempts is needed.
*   **Out-of-Order Information:** If a user provides all information upfront (e.g., "I want 2 shirts, size M, deliver to Yangon, COD"), the AI might extract it all, but the `FlowManager`'s sequential checks might still trigger unnecessary prompts if the logic isn't perfectly aligned with the merged data state.

### 3. Merchant Onboarding Bugs

*   **Missing Default Scripts:** If a new merchant is created but the `merchant_scripts` table isn't populated with default values for that `shop_id`, the system will fall back to the hardcoded defaults in `app/core/scripts.py`. While functional, this bypasses the intended database-driven script management.
*   **Invalid Webhook Configuration:** If the `tg_bot_token` is invalid or the webhook fails to set during onboarding, the merchant will silently fail to receive messages. A robust verification step is needed during onboarding.

### 4. Order Confirmation Bugs

*   **Stock Depletion Race Condition:** The system checks stock when displaying the menu but doesn't appear to decrement stock atomically when an order is confirmed. Two concurrent orders for the last item could both be confirmed, leading to overselling.

### 5. Screenshot Verification Bugs

*   **Fake/Reused Screenshots:** The system relies entirely on manual admin review for screenshots. There is no automated check for reused transaction IDs or manipulated images, making it vulnerable to basic fraud.

### 6. Audit Logging Bugs

*   **Missing Context:** Some audit logs might lack sufficient context (e.g., the specific fields that changed during an `ORDER_STATUS_CHANGE`). This makes debugging complex state transitions difficult.

### 7. Script Loading Bugs

*   **Cache Invalidation:** If `ScriptService` uses caching (as suggested in the design docs), updating a script in the dashboard might not immediately reflect in the bot's responses unless the cache is properly invalidated.

### 8. Order Lifecycle Bugs

*   **Stale Orders:** Orders that are abandoned mid-conversation (e.g., at `ASK_ADDRESS`) will remain in the `orders` table indefinitely. A background job is needed to transition these to `CANCELLED` or an `ABANDONED` state after a timeout to keep the active order queries fast.
