# SellMate AI Backend: Stability Hardening Phase

## 1. Introduction

This document details the stability hardening phase for the SellMate AI backend. Following the initial refactoring into a multi-tenant SaaS platform, this phase focuses on ensuring production safety, reliability, concurrency safety, and scalable workflow stability. The goal is to prepare SellMate for real beta merchants by addressing critical production issues.

## 2. Hardening Requirements and Implementation Strategy

### 2.1. Conversation Lock System
*   **Goal:** Prevent race conditions and inconsistent workflow states caused by simultaneous processing of multiple messages in the same conversation.
*   **Implementation:** A per-conversation locking mechanism. A `LockManager` service will be introduced, likely using a database-based lock (or Redis-ready abstraction) with auto-release on completion/failure and timeout protection.

### 2.2. Webhook Idempotency / Deduplication
*   **Goal:** Avoid duplicate orders, notifications, and payment reviews caused by Telegram's webhook retries.
*   **Implementation:** An idempotency layer will store processed `update_id`s. A middleware or dedicated service will check if an event has already been processed before proceeding.

### 2.3. Validation Layer
*   **Goal:** Ensure data integrity by validating AI-extracted fields (phone numbers, addresses, quantities, etc.) before saving.
*   **Implementation:** A centralized `ValidationService` will be implemented. It will define validation rules for each field and trigger re-asking the customer if data is invalid, preventing broken workflow states.

### 2.4. Conversation Session Timeout
*   **Goal:** Handle inactive customers by expiring stale conversations and archiving/resetting stale orders.
*   **Implementation:** A background cleanup worker will periodically check for conversations with no activity for a configurable duration (defaulting to 24 hours) and perform necessary cleanup.

### 2.5. Human Takeover Mode Hardening
*   **Goal:** Prevent simultaneous replies from the bot and human admins.
*   **Implementation:** A strict conversation ownership system with two modes: `BOT_MODE` and `HUMAN_MODE`. The bot will be explicitly disabled during `HUMAN_MODE`, with clean state transitions and manual handover tracking.

### 2.6. Database-Based Script System
*   **Goal:** Enable merchant-specific script customization and improve scalability.
*   **Implementation:** Move scripts from `script.py` to a `merchant_scripts` table. Implement a script loading service with caching support and fallback to default scripts.

### 2.7. Notification Reliability Improvements
*   **Goal:** Ensure reliable delivery of Telegram notifications to merchant admins.
*   **Implementation:** Enhance the notification system with exponential backoff retries, failure logging, dead-letter queue support, and status tracking.

### 2.8. Order State Machine Hardening
*   **Goal:** Enforce strict and predictable order state transitions.
*   **Implementation:** Implement a centralized state manager with defined transition rules, invalid transition protection, and comprehensive logging.

### 2.9. Structured Error Handling
*   **Goal:** Prevent silent failures and ensure workflow recovery.
*   **Implementation:** A centralized error handling architecture with safe try/catch wrappers, structured logging, safe fallback replies, and error categorization.

### 2.10. Audit Log Improvements
*   **Goal:** Provide a full audit trail for production debugging and transparency.
*   **Implementation:** Extend the audit log system to track all significant actions (bot/admin replies, payment actions, status changes, errors, retries) with detailed metadata.

### 2.11. Security Hardening
*   **Goal:** Implement basic production security layers.
*   **Implementation:** Enhance merchant isolation validation, upload validation (safe filenames, payload limits), and prepare for rate limiting.

### 2.12. Dashboard Query Optimization
*   **Goal:** Ensure the dashboard remains fast as the number of orders grows.
*   **Implementation:** Optimize queries with proper indexing, pagination, and lightweight summary queries.

### 2.13. Background Task Architecture
*   **Goal:** Provide a future-ready async architecture for various tasks.
*   **Implementation:** Refine the worker system to be queue-friendly and easily extendable for tasks like OCR, retries, cleanup, and AI extraction.

### 2.14. Codebase Cleanup
*   **Goal:** Improve readability, maintainability, and production stability.
*   **Implementation:** Further refactor messy logic into clean layers (workflow, service, repository, notification, validation, storage, payment) and reduce coupling.

## 3. Updated Database Schema for Hardening

### `processed_webhooks` Table
To support idempotency.
```sql
CREATE TABLE IF NOT EXISTS processed_webhooks (
    update_id BIGINT PRIMARY KEY,
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    processed_at TIMESTAMP DEFAULT NOW()
);
```

### `merchant_scripts` Table
To support customizable scripts.
```sql
CREATE TABLE IF NOT EXISTS merchant_scripts (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    script_key TEXT NOT NULL,
    content TEXT NOT NULL,
    active_status BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(shop_id, script_key)
);
```

### `conversation_locks` Table
To support conversation-level locking (if using DB-based locks).
```sql
CREATE TABLE IF NOT EXISTS conversation_locks (
    shop_id VARCHAR(20) NOT NULL,
    chat_id BIGINT NOT NULL,
    locked_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    PRIMARY KEY(shop_id, chat_id)
);
```

## 4. Conclusion

This hardening phase is critical for moving SellMate from a refactored prototype to a production-ready operating system for merchants. By focusing on deterministic workflows, reliability, and safety, the system will provide a stable foundation for Myanmar online shops to scale their operations.
