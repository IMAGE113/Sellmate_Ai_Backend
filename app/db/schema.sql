-- SellMate AI Multi-tenant SaaS Production Schema

-- 1. Businesses (Merchants)
CREATE TABLE IF NOT EXISTS businesses (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    owner_name VARCHAR(100),
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    category VARCHAR(50) DEFAULT 'general',
    requirements_text TEXT,
    tg_bot_token TEXT,
    is_human_takeover_active BOOLEAN DEFAULT FALSE,
    workflow_config JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(20) DEFAULT 'ACTIVE', -- ACTIVE, PENDING, SUSPENDED, ARCHIVED
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_businesses_shop_id ON businesses(shop_id);
CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);

-- 2. Merchant Admins (RBAC)
CREATE TABLE IF NOT EXISTS merchant_admins (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) REFERENCES businesses(shop_id),
    user_id INTEGER, -- External user ID if applicable
    role VARCHAR(20) DEFAULT 'ADMIN', -- ADMIN, SUPER_ADMIN, OPERATOR
    active_status BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. Products / Menu
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) REFERENCES businesses(shop_id),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    price DECIMAL(12, 2) NOT NULL,
    stock INTEGER DEFAULT 0,
    category VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_products_shop_id ON products(shop_id);

-- 3.1 Product Variants
CREATE TABLE IF NOT EXISTS product_variants (
    id SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id) ON DELETE CASCADE,
    shop_id VARCHAR(50) REFERENCES businesses(shop_id),
    variant_name VARCHAR(100) NOT NULL, -- e.g., 'Small', 'Large', 'Red', 'Blue'
    price DECIMAL(12, 2), -- Optional: Override parent price
    stock INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(product_id, variant_name)
);
CREATE INDEX IF NOT EXISTS idx_variants_product_id ON product_variants(product_id);
CREATE INDEX IF NOT EXISTS idx_variants_shop_id ON product_variants(shop_id);

-- 4. Orders
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id),
    shop_id VARCHAR(50) REFERENCES businesses(shop_id),
    chat_id BIGINT NOT NULL,
    customer_name VARCHAR(100),
    total_price DECIMAL(12, 2),
    status VARCHAR(50) DEFAULT 'NEW_CHAT',
    extracted_data JSONB DEFAULT '{}'::jsonb,
    timeline JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_orders_shop_id ON orders(shop_id);
CREATE INDEX IF NOT EXISTS idx_orders_chat_id ON orders(chat_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- 5. Task Queue (Standardized Payload)
CREATE TABLE IF NOT EXISTS task_queue (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) NOT NULL,
    queue_name VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- pending, processing, retrying, completed, failed, dead_letter
    retry_count INTEGER DEFAULT 0,
    worker_id VARCHAR(100),
    error_message TEXT,
    correlation_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,
    heartbeat TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_task_queue_status_queue ON task_queue(status, queue_name);
CREATE INDEX IF NOT EXISTS idx_task_queue_shop_id ON task_queue(shop_id);

-- 6. Conversation Locks (Deduplication)
CREATE TABLE IF NOT EXISTS conversation_locks (
    shop_id VARCHAR(50) NOT NULL,
    chat_id BIGINT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    locked_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (shop_id, chat_id)
);

-- 7. Idempotency (Processed Webhooks)
CREATE TABLE IF NOT EXISTS processed_webhooks (
    update_id BIGINT PRIMARY KEY,
    shop_id VARCHAR(50) NOT NULL,
    processed_at TIMESTAMP DEFAULT NOW()
);

-- 8. Merchant Scripts (Custom Responses)
CREATE TABLE IF NOT EXISTS merchant_scripts (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) REFERENCES businesses(shop_id),
    script_key VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    active_status BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(shop_id, script_key)
);

-- 9. Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id),
    shop_id VARCHAR(50) NOT NULL,
    order_id INTEGER,
    event_type VARCHAR(50) NOT NULL,
    description TEXT,
    actor_source VARCHAR(50), -- bot, system, admin, customer
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_shop_id ON audit_logs(shop_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);

-- 10. Worker Health
CREATE TABLE IF NOT EXISTS worker_health (
    worker_id VARCHAR(100) PRIMARY KEY,
    last_heartbeat TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'active',
    active_jobs INTEGER DEFAULT 0,
    memory_usage_mb FLOAT,
    started_at TIMESTAMP DEFAULT NOW()
);

-- 11. Metrics Rollups
CREATE TABLE IF NOT EXISTS metrics_rollups (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    rollup_type VARCHAR(20) NOT NULL, -- 1m, 5m, 1h, 1d
    metric_value FLOAT NOT NULL,
    dimensions JSONB DEFAULT '{}'::jsonb,
    period_start TIMESTAMP NOT NULL,
    UNIQUE(metric_name, rollup_type, period_start, dimensions)
);

-- 12. Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id),
    shop_id VARCHAR(50) NOT NULL,
    order_id INTEGER,
    admin_chat_id BIGINT NOT NULL,
    type VARCHAR(50),
    message TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending', -- pending, sent, failed
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 13. Merchant Configuration History
CREATE TABLE IF NOT EXISTS merchant_config_history (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) NOT NULL,
    config_key VARCHAR(100) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    actor_id INTEGER,
    actor_type VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_config_history_shop_id ON merchant_config_history(shop_id);

-- 14. System Metrics
CREATE TABLE IF NOT EXISTS system_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value FLOAT NOT NULL,
    dimensions JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_system_metrics_name ON system_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_system_metrics_created_at ON system_metrics(created_at);