-- SellMate Final Production Schema

-- Refactored Queue Table (Phase 2 & 3)
CREATE TABLE IF NOT EXISTS task_queue (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) NOT NULL,
    queue_name VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL, -- Standardized Payload
    status VARCHAR(20) DEFAULT 'pending', -- pending, processing, retrying, completed, failed, dead_letter, cancelled
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
CREATE INDEX IF NOT EXISTS idx_task_queue_correlation_id ON task_queue(correlation_id);

-- Worker Health Monitoring (Phase 4)
CREATE TABLE IF NOT EXISTS worker_health (
    worker_id VARCHAR(100) PRIMARY KEY,
    last_heartbeat TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'active',
    active_jobs INTEGER DEFAULT 0,
    memory_usage_mb FLOAT,
    started_at TIMESTAMP DEFAULT NOW()
);

-- Metrics Rollups (Phase 5)
CREATE TABLE IF NOT EXISTS metrics_rollups (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    rollup_type VARCHAR(20) NOT NULL, -- 1m, 5m, 1h, 1d
    metric_value FLOAT NOT NULL,
    dimensions JSONB DEFAULT '{}'::jsonb,
    period_start TIMESTAMP NOT NULL,
    UNIQUE(metric_name, rollup_type, period_start, dimensions)
);

-- Analytics & Audit (Already exists, but ensuring indexes)
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_daily_analytics_shop_date ON daily_analytics(shop_id, date);

-- Merchant Configuration History (Final Hardening)
CREATE TABLE IF NOT EXISTS merchant_config_history (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(50) NOT NULL,
    config_key VARCHAR(100) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    actor_id INTEGER, -- Admin who made the change
    actor_type VARCHAR(20), -- 'admin', 'system'
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_config_history_shop_id ON merchant_config_history(shop_id);

-- Merchant Lifecycle Status
ALTER TABLE businesses ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'ACTIVE'; -- ACTIVE, SUSPENDED, ARCHIVED
CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);
