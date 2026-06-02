# SellMate: Database Performance Report

This report outlines the optimizations applied to the SellMate database to ensure scalability and high performance for the merchant operating system.

## 1. Applied Optimizations

### 1.1. Indexing Strategy
We have implemented several critical indexes to optimize frequent queries:
- **Tenant Isolation:** `idx_businesses_shop_id`, `idx_products_shop_id`, `idx_orders_shop_id_chat_id` ensure that multi-tenant data retrieval is fast and secure.
- **Workflow & Queues:** `idx_task_queue_status_queue` and `idx_task_queue_correlation_id` optimize job fetching and request tracing.
- **Observability:** `idx_audit_logs_created_at` and `idx_audit_logs_order_id` speed up timeline and history views.
- **Analytics:** `idx_daily_analytics_shop_date` ensures fast retrieval for merchant dashboards.

### 1.2. Schema Normalization
- Standardized the `task_queue` with a `JSONB` payload to support flexible yet structured data.
- Introduced `metrics_rollups` to store pre-aggregated metrics, reducing the load on the raw `system_metrics` table during dashboard reads.

## 2. Query Improvements

| Query Area | Improvement | Expected Gain |
| :--- | :--- | :--- |
| **Queue Fetching** | Added `SKIP LOCKED` and combined status/queue index. | 10x reduction in contention under high load. |
| **Merchant Dashboard** | Switched from raw audit logs to `metrics_rollups` for trends. | 100x faster reads for long-term analytics. |
| **Order History** | Implemented composite index on `shop_id` and `chat_id`. | Constant-time lookup for active customer sessions. |
| **Worker Health** | Heartbeat updates use `ON CONFLICT` for single-row efficiency. | Minimal overhead for high-frequency worker updates. |

## 3. Scalability Bottlenecks & Recommendations
- **Audit Log Growth:** As the system scales, the `audit_logs` table will grow significantly. We recommend implementing table partitioning by `created_at` or a retention policy for logs older than 90 days.
- **JSONB Search:** While flexible, searching inside `JSONB` fields can be slow. We use indexes on top-level fields and recommend keeping nested data shallow.
