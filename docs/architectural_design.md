# SellMate AI Backend Architectural Design

## 1. Introduction

This document outlines the proposed architectural design for refactoring the SellMate AI backend. The primary goal is to transform the existing system into a production-ready, multi-tenant SaaS platform, focusing on reliability, scalability, clean architecture, multi-tenancy safety, maintainability, and workflow consistency. The design prioritizes stable merchant operations over advanced AI features, ensuring a predictable and reliable experience for online shops in Myanmar.

## 2. Core System Requirements and Design Principles

The refactoring will address the following core system requirements:

*   **Multi-Tenant SaaS Architecture:** Strict data isolation for each merchant, with all database queries including `merchant_id` filtering.
*   **Order Status System:** Implementation of a robust order workflow with defined states, clean state transitions, transition validation, and order timeline tracking.
*   **Script-Based Conversation Engine:** Refactoring AI logic into a deterministic workflow system driven by merchant-defined requirements and predefined scripts, avoiding AI hallucinations.
*   **Structured Memory System:** A lightweight memory architecture focused on extracting and storing structured data points from conversations, optimizing token usage.
*   **Payment Review Flow:** A manual payment verification system including screenshot saving, payment review record creation, merchant admin notifications, and automated customer updates.
*   **Admin Telegram Chat IDs:** Storing merchant Telegram admin IDs in the database for scalable notification management.
*   **Notification System:** A reliable notification architecture with retry mechanisms, failure logging, a notification queue, and async-safe delivery.
*   **File Storage Structure:** An organized and scalable file storage system for uploads, structured by `merchant_id` and `order_id`.
*   **Dashboard Architecture:** Design for a merchant dashboard with fast queries, pagination, filtering, and scalable structure for displaying pending payments, recent orders, confirmed orders, cancelled orders, and order counts.
*   **Human Takeover Mode:** Features to pause the bot, allow manual admin replies, and resume automation with clean conversation ownership handling.
*   **Fallback System:** Implementation of try/catch fallback replies, default safe responses, and an error recovery system to prevent silent AI failures.
*   **Audit Log System:** An event logging system to track bot replies, admin actions, payment confirmations/rejections, order status changes, errors, and notification failures.
*   **Background Tasks / Async System:** Architecture prepared for scaling with queue-ready design, background worker compatibility, and async-safe code structure for tasks like OCR, notifications, AI parsing, and uploads.
*   **Security & Validation:** Comprehensive input validation, upload validation, merchant isolation checks, safe database queries, and rate limiting preparation.
*   **Codebase Refactor:** Improvement of architecture, clean separation of responsibilities into service, workflow, notification, storage, payment, and dashboard layers, reducing spaghetti logic, and enhancing maintainability, readability, and scalability.

## 3. Proposed Database Schema Changes

To support the new requirements, the existing database schema will be extended and modified. Key changes include:

### `businesses` Table

No significant changes to the core `businesses` table, but new fields might be added for merchant settings related to conversation flow.

```sql
CREATE TABLE businesses (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(20) UNIQUE NOT NULL,  -- SM-XXXXXX
    name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    category TEXT, -- This will be deprecated or used as a fallback. Replaced by 'requirements_text' and structured settings.
    requirements_text TEXT, -- Raw text instructions from merchant for AI behavior
    tg_bot_token TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    -- New fields for merchant settings (examples)
    setting_require_name BOOLEAN DEFAULT FALSE,
    setting_require_phone BOOLEAN DEFAULT FALSE,
    setting_require_address BOOLEAN DEFAULT FALSE,
    setting_require_size BOOLEAN DEFAULT FALSE,
    setting_require_color BOOLEAN DEFAULT FALSE,
    setting_require_payment_screenshot BOOLEAN DEFAULT FALSE
);
```

### `orders` Table

Addition of `status` field with new states, `timeline` for tracking status changes, and structured `extracted_data` for conversation memory.

```sql
CREATE TYPE order_status AS ENUM (
    'NEW_CHAT',
    'COLLECTING_INFO',
    'WAITING_PAYMENT',
    'PAYMENT_PENDING_REVIEW',
    'PAYMENT_CONFIRMED',
    'READY_TO_SHIP',
    'COMPLETED',
    'CANCELLED'
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    chat_id BIGINT NOT NULL,
    customer_name TEXT,
    phone_no VARCHAR(20),
    items JSONB NOT NULL,  -- Store as JSONB for flexibility
    total_price INTEGER NOT NULL,
    status order_status DEFAULT 'NEW_CHAT', -- New ENUM type
    timeline JSONB DEFAULT '[]', -- Array of {timestamp, status, actor} for audit
    extracted_data JSONB DEFAULT '{}', -- Structured memory from conversation
    created_at TIMESTAMP DEFAULT NOW()
);
```

### `products` Table

No significant changes.

```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    stock INTEGER DEFAULT 0,
    category TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### New Tables

#### `merchant_admins` Table

To store Telegram admin IDs for notifications.

```sql
CREATE TABLE merchant_admins (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    telegram_chat_id BIGINT NOT NULL,
    role TEXT NOT NULL, -- e.g., 'owner', 'manager', 'staff'
    active_status BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### `payment_reviews` Table

To manage the manual payment verification workflow.

```sql
CREATE TYPE payment_review_status AS ENUM (
    'PENDING',
    'CONFIRMED',
    'REJECTED'
);

CREATE TABLE payment_reviews (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    order_id INTEGER NOT NULL REFERENCES orders(id),
    screenshot_url TEXT NOT NULL,
    status payment_review_status DEFAULT 'PENDING',
    reviewer_id INTEGER, -- References merchant_admins.id or similar admin user table
    review_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### `notifications` Table

To queue and track notifications.

```sql
CREATE TYPE notification_type AS ENUM (
    'PAYMENT_PENDING',
    'PAYMENT_CONFIRMED',
    'PAYMENT_REJECTED',
    'NEW_ORDER',
    'ORDER_UPDATE'
);

CREATE TYPE notification_status AS ENUM (
    'PENDING',
    'SENT',
    'FAILED',
    'RETRYING'
);

CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    order_id INTEGER REFERENCES orders(id),
    admin_chat_id BIGINT, -- Target admin chat ID
    type notification_type NOT NULL,
    message TEXT NOT NULL,
    status notification_status DEFAULT 'PENDING',
    retries INTEGER DEFAULT 0,
    last_attempt TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### `audit_logs` Table

For comprehensive event logging.

```sql
CREATE TYPE log_event_type AS ENUM (
    'BOT_REPLY',
    'ADMIN_ACTION',
    'PAYMENT_CONFIRMED',
    'PAYMENT_REJECTED',
    'ORDER_STATUS_CHANGE',
    'ERROR',
    'NOTIFICATION_FAILURE',
    'HUMAN_TAKEOVER_START',
    'HUMAN_TAKEOVER_END'
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    order_id INTEGER REFERENCES orders(id),
    event_type log_event_type NOT NULL,
    description TEXT,
    actor_source TEXT, -- e.g., 'bot', 'admin', 'system'
    details JSONB DEFAULT '{}', -- Additional structured details
    created_at TIMESTAMP DEFAULT NOW()
);
```

## 4. Architectural Layers and Responsibilities

The codebase will be refactored into distinct layers to improve modularity, maintainability, and scalability.

*   **API Layer (`app/api/`):** Handles incoming requests (webhooks, dashboard API calls), performs basic validation, and routes requests to the appropriate service layer.
*   **Service Layer (`app/services/`):** Contains the core business logic. This layer will be further subdivided:
    *   `auth_service.py`: Handles authentication and authorization.
    *   `merchant_service.py`: Manages merchant-specific settings and data.
    *   `order_service.py`: Manages order creation, updates, and status transitions.
    *   `conversation_service.py`: Orchestrates the script-based conversation flow, interacts with the AI/scripting engine, and updates structured memory.
    *   `payment_service.py`: Handles payment-related logic, including review flow.
    *   `notification_service.py`: Manages sending and queuing notifications.
    *   `storage_service.py`: Abstracts file storage operations.
    *   `dashboard_service.py`: Provides data for the merchant dashboard.
*   **Workflow Layer (`app/workflow/`):** This new layer will house the deterministic conversation flow logic, state machines, and field completion checkers.
    *   `flow_manager.py`: Manages conversation states and transitions.
    *   `script_engine.py`: Executes predefined reply scripts based on merchant settings.
    *   `field_checker.py`: Determines missing required fields.
*   **Data Access Layer (`app/db/`):** Responsible for all database interactions, ensuring `shop_id` filtering on all queries. This layer will provide an abstraction over `asyncpg`.
*   **Worker Layer (`app/workers/`):** Contains background workers for processing asynchronous tasks from queues (e.g., `order_worker.py`, `notification_worker.py`).
*   **Core Utilities (`app/core/`):** Configuration, logging, and other cross-cutting concerns.

## 5. Multi-Tenancy and Security

*   **Data Isolation:** All database queries will be strictly scoped by `shop_id` or `business_id`. Middleware will enforce this by extracting the `shop_id` from the JWT token for authenticated requests.
*   **Input Validation:** Robust validation will be implemented at the API layer to prevent malicious inputs.
*   **Upload Validation:** File uploads will be validated for type, size, and safe filenames.
*   **Rate Limiting:** Preparation for rate limiting on critical endpoints (e.g., authentication, webhook) to prevent abuse.

## 6. Workflow Consistency and Predictable Behavior

*   **Script-Based Responses:** The AI will primarily act as a data extractor and intent classifier, with actual bot replies driven by predefined scripts and merchant settings. This ensures predictable behavior and avoids AI hallucinations.
*   **State Machine for Orders:** A clear state machine will govern order statuses, ensuring valid transitions and preventing inconsistent states.
*   **Human Takeover:** A mechanism to pause AI automation and allow manual intervention by merchant admins, with clear logging of ownership changes.

## 7. File Storage

Uploads will be stored in a structured manner:

`uploads/merchant_id/order_id/payment/` for payment screenshots.
`uploads/merchant_id/order_id/attachments/` for other order-related attachments.

Safe filenames and size limits will be enforced.

## 8. Notification and Audit Systems

*   **Notifications:** A dedicated notification queue will handle various notification types (payment, order updates) with retry logic and failure logging.
*   **Audit Logs:** A comprehensive audit log will track all significant events, including timestamps, `merchant_id`, `order_id`, event type, and actor source.

## 9. Dashboard Architecture

The dashboard will consume data from the API layer, which will leverage optimized queries with pagination and filtering capabilities from the `dashboard_service`.

## 10. Conclusion

This architectural design provides a roadmap for transforming the SellMate AI backend into a stable, reliable, and scalable multi-tenant SaaS platform. By focusing on structured workflows, clear separation of concerns, and robust data isolation, the system will effectively address the pain points of Myanmar online shops and reduce operational chaos.
