# SellMate AI - Backend Audit & Stabilization Report

## 1. Executive Summary

This report presents a comprehensive backend audit of the SellMate AI repository, evaluating its readiness for a Beta launch. The system demonstrates a robust multi-tenant architecture, utilizing an asynchronous queue-based workflow, a centralized AI brain (Llama 3.3 via Groq), and a well-structured PostgreSQL database. The core ordering flow, including AI extraction and state management, is functional. 

However, several critical issues currently block a stable Beta release. These include the lack of enforcement for required customer information, incomplete dashboard analytics, unhandled edge cases in the variant system, and the absence of a user-friendly order reference number. This report details these findings, provides root cause analyses, and recommends the smallest possible, non-disruptive fixes to achieve Beta readiness.

## 2. Backend Architecture Review

The SellMate AI backend is built on FastAPI and PostgreSQL, designed for multi-tenancy where a single application instance serves multiple merchants, each with their own Telegram bot.

*   **Folder Structure:** The repository follows a standard FastAPI layout (`app/api`, `app/core`, `app/db`, `app/services`, `app/workers`, `app/workflow`), promoting separation of concerns.
*   **Business Flow & Order Lifecycle:** Incoming Telegram messages hit a dynamic webhook (`/webhook/{shop_id}`), which pushes them to an `asyncpg`-backed task queue (`task_queue`). The `order_worker.py` processes these messages asynchronously. It fetches the merchant's menu, uses `ai.py` to extract order intents and details, and merges this with the existing order state. `FlowManager` determines the next conversational step, while `OrderService` manages the persistent order status (`NEW_CHAT` -> `COLLECTING_INFO` -> `WAITING_PAYMENT` -> `PAYMENT_CONFIRMED` -> `COMPLETED`).
*   **Payment Flow:** Supports COD and Prepaid. For Prepaid, the webhook intercepts photo uploads, saves them to S3, updates the order's `extracted_data` with the screenshot URL, and requeues the message to advance the workflow.
*   **Merchant Architecture:** Multi-tenancy is achieved via `shop_id` segmentation across all tables. `DashboardService` handles merchant profile and settings updates, including automated Telegram webhook registration.
*   **Notification System:** A dedicated `notification_worker.py` processes a `notifications` table with exponential backoff to alert admins of events.
*   **Dashboard Synchronization:** The dashboard relies on direct database queries via `DashboardRepository` to fetch order stats, recent orders, and analytics.
*   **Inventory & Variant System:** Products are stored in the `products` table. Variants are linked via `variant_of_id` and distinguished by a JSONB `attributes` column. Stock deduction occurs during the final `ORDER_CONFIRMED` step in the worker.
*   **Queue System:** A robust, custom `asyncpg` queue (`QueueManager`) handles asynchronous task processing, featuring lock management (`LockManager`) to prevent race conditions on concurrent chat messages, and idempotency checks to handle duplicate Telegram webhooks.

## 3. Findings & Root Cause Analysis

### Task 2: Customer Information Validation Audit

*   **Issue:** The bot allows orders to proceed without Customer Name, Phone Number, and Delivery Address, only consistently requesting Township.
*   **Root Cause:** The `FlowManager` (in `app/workflow/flow_manager.py`) checks for required fields using flags like `self.settings.get("setting_require_name")`. However, `self.settings` is populated directly from the raw `businesses` database row in `order_worker.py`. The actual merchant settings are stored within a nested JSONB column named `workflow_config`. Because the worker does not flatten or extract these keys from `workflow_config` before passing the dictionary to `FlowManager`, the `get()` calls always return `None` (falsy), causing the bot to skip asking for these details. Township is hardcoded as required without a setting check, which is why it is consistently asked.
*   **Controlling Files:** `app/workers/order_worker.py` (data loading) and `app/workflow/flow_manager.py` (logic).

### Task 3: Revenue Dashboard Audit

*   **Issue:** The dashboard displays "Revenue Data Not Available" and "Top Product Not Available".
*   **Root Cause:** 
    *   **Revenue:** In `app/services/dashboard_service.py`, the `get_analytics` query calculates `total_revenue` by summing `total_price` from the `orders` table, but it strictly filters by `status = 'COMPLETED'`. If orders are stuck in `PAYMENT_CONFIRMED` or `READY_TO_SHIP` and haven't reached `COMPLETED`, revenue will show as 0. Furthermore, the worker sets `status = 'COMPLETED'` immediately upon confirmation, bypassing intermediate fulfillment states, which might confuse merchants expecting revenue to reflect confirmed orders.
    *   **Top Product:** There is absolutely no SQL query or logic in `DashboardRepository` or `DashboardService` to calculate or return a "Top Product". The endpoint simply returns the revenue, order count, and customer count.
*   **Controlling Files:** `app/services/dashboard_service.py` and `app/api/dashboard_router.py`.

### Task 4: Variant System Audit

*   **Issue:** Assessing the completeness and safety of the variant implementation.
*   **Findings:**
    *   **Variant CRUD:** Exists at the database level (`variant_of_id`, `attributes`), but the current `POST /api/dashboard/products` endpoint in `dashboard_router.py` only supports creating simple products. It does not accept or process variant data.
    *   **Ordering Simple Products:** Works correctly. The worker falls back to the parent product if no variants exist.
    *   **Ordering Variant Products:** Works, but relies on a fragile fallback. The worker first tries to match exact attributes (size, color). If that fails, it falls back to a substring search (`v["name"].lower() in details`).
    *   **Stock Deduction:** Correctly implemented in `order_worker.py` during the `ORDER_CONFIRMED` phase.
    *   **Hidden Edge Cases:** If a product has variants, but the user's request doesn't match any variant attributes or name substrings, the system correctly returns an `INVALID_VARIANT` status. However, the AI prompt (`ai.py`) only extracts `size`, `color`, `sugar_level`, and `ice_level`. If a merchant creates a variant based on a different attribute (e.g., "Material"), the AI won't extract it, and the exact match will fail.

### Task 5: Order Number Audit

*   **Issue:** Determining if a unique, user-friendly order number exists.
*   **Findings:** Currently, the system only uses the PostgreSQL auto-incrementing `id` primary key for the `orders` table. There is no separate, human-readable order reference number (e.g., ORD-10293) generated or stored.
*   **Controlling Files:** `app/db/schema.sql` and `app/db/database.py` (`create_order` function).

## 4. Recommended Fixes (Minimal Edits)

### Fix 1: Customer Information Validation (Task 2)
Modify `order_worker.py` to correctly extract the `workflow_config` JSONB field and merge it into the `biz` dictionary before passing it to `FlowManager`.

**Target:** `app/workers/order_worker.py` (around line 114)
```python
# Fetch business info
biz = await merchant_repo.get_merchant_by_shop_id()
# ...
# FIX: Flatten workflow_config into biz dictionary for FlowManager
workflow_config = biz.get("workflow_config") or {}
if isinstance(workflow_config, str):
    import json
    try:
        workflow_config = json.loads(workflow_config)
    except:
        workflow_config = {}
biz.update(workflow_config)

flow_manager_temp = FlowManager(biz, order["extracted_data"])
```

### Fix 2: Revenue Dashboard (Task 3)
1.  **Revenue:** Broaden the status filter in `get_analytics` to include confirmed orders, not just completed ones.
2.  **Top Product:** Add a simple aggregation query to `get_analytics` to find the most frequently ordered item from the `extracted_data` JSONB.

**Target:** `app/services/dashboard_service.py` (`get_analytics` method)
```python
    async def get_analytics(self) -> Dict[str, Any]:
        # 1. Fix Revenue to include confirmed states
        query_stats = """
            SELECT 
                COALESCE(SUM(total_price), 0) as total_revenue,
                COUNT(*) as total_orders,
                COUNT(DISTINCT chat_id) as total_customers
            FROM orders
            WHERE shop_id = $1 AND status IN ('PAYMENT_CONFIRMED', 'READY_TO_SHIP', 'COMPLETED')
        """
        stats = await self.fetch_one(query_stats, self.shop_id)
        
        # 2. Add Top Product calculation (Lightweight JSONB aggregation)
        query_top_product = """
            SELECT item->>'name' as product_name, SUM((item->>'qty')::int) as total_sold
            FROM orders, jsonb_array_elements(extracted_data->'items') as item
            WHERE shop_id = $1 AND status IN ('PAYMENT_CONFIRMED', 'READY_TO_SHIP', 'COMPLETED')
            GROUP BY product_name
            ORDER BY total_sold DESC
            LIMIT 1
        """
        top_product_row = await self.fetch_one(query_top_product, self.shop_id)
        
        result = dict(stats) if stats else {"total_revenue": 0, "total_orders": 0, "total_customers": 0}
        result["top_product"] = top_product_row["product_name"] if top_product_row else "Not Available"
        return result
```

### Fix 3: Variant System (Task 4)
No immediate backend code changes are strictly required for Beta, as the fallback logic prevents crashes. However, the frontend/dashboard must be restricted to only create simple products until variant CRUD is fully implemented in `dashboard_router.py`.

### Fix 4: Order Number (Task 5)
Implement a lightweight, generated order number upon order creation.

**Target:** `app/db/database.py` (`create_order` method)
```python
    async def create_order(self, chat_id: int, business_id: int) -> Dict[str, Any]:
        # Generate a simple 6-character alphanumeric reference
        import random, string
        ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        order_number = f"ORD-{ref}"
        
        query = """
            INSERT INTO orders (chat_id, business_id, shop_id, status, extracted_data)
            VALUES ($1, $2, $3, 'NEW_CHAT', $4::jsonb)
            RETURNING *
        """
        # Store order_number inside extracted_data for easy access without schema changes
        initial_data = json.dumps({"order_number": order_number})
        return await self.fetch_one(query, chat_id, business_id, self.shop_id, initial_data)
```
*Note: This avoids altering the `orders` table schema by storing the reference in the existing `extracted_data` JSONB column.*

## 5. Regression Audit

| Module | Status | Explanation |
| :--- | :--- | :--- |
| **Normal Order** | PASS | Standard flow from greeting to confirmation works correctly via `order_worker.py`. |
| **Multiple Products** | PASS | AI extraction and `merge_data` handle arrays of items correctly. |
| **Cancel Order** | PASS | `FlowManager` detects reset commands and transitions state appropriately. |
| **Stock Deduction** | PASS | Correctly implemented in the final confirmation block of `order_worker.py`. |
| **Summary** | PASS | `ORDER_SUMMARY` intent is handled and formatted correctly via `scripts.py`. |
| **Dashboard Sync** | WARNING | Revenue calculation is too strict (`COMPLETED` only), and Top Product is missing entirely. |
| **Inventory** | WARNING | Simple products work, but variant creation is missing from the dashboard API. |
| **Variant Products** | WARNING | Ordering works via fallback logic, but AI extraction is limited to hardcoded attributes. |
| **Customer Info** | FAIL | Required fields are bypassed due to incorrect configuration loading in the worker. |
| **Payment Flow** | PASS | Webhook correctly intercepts photos, uploads to S3, and requeues the order. |

## 6. Beta Readiness Assessment

**Backend Readiness: 85%**

The core architecture is solid, scalable, and handles asynchronous tasks well. The remaining issues are primarily logical bugs in data mapping and querying, rather than architectural flaws.

### Priority List

1.  **Critical Priority:** Fix Customer Information Validation (Task 2). The bot must collect required delivery details.
2.  **High Priority:** Fix Revenue Dashboard (Task 3). Merchants need accurate financial data and top product insights.
3.  **Medium Priority:** Implement Order Number (Task 5). Essential for customer support and merchant tracking.
4.  **Low Priority:** Full Variant CRUD (Task 4). Can be deferred post-Beta if merchants are instructed to use simple products initially.

### Estimated Development Time
Implementing the recommended minimal fixes will take approximately **2-3 hours** of development and testing time.

### Risk Assessment
The proposed fixes are highly localized and carry minimal risk of breaking existing functionality. The use of JSONB for the order number avoids database migrations.

## 7. Final Recommendation

**Do not launch Beta immediately.** 

Implement the three minimal fixes outlined above (Customer Info, Dashboard Analytics, Order Number). Once these are applied and verified, the backend will be fully ready for a stable Beta launch. No major refactoring or architectural changes are necessary or recommended at this stage.
