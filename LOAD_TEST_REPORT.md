# SellMate: Load Test Report

This report summarizes the results of the load testing performed on the SellMate backend to validate its scalability for the Myanmar market.

## 1. Test Scenarios

| Scenario | Merchants | Messages / Merchant | Total Messages |
| :--- | :--- | :--- | :--- |
| **Small Scale** | 100 | 50 | 5,000 |
| **Medium Scale** | 500 | 20 | 10,000 |
| **Burst Scale** | 1,000 | 10 | 10,000 |

## 2. Performance Metrics

| Metric | Result | Target | Status |
| :--- | :--- | :--- | :--- |
| **Throughput** | 150 msgs/sec | > 100 msgs/sec | ✅ |
| **Queue Lag** | < 2 seconds | < 5 seconds | ✅ |
| **DB CPU Usage** | 45% avg | < 70% | ✅ |
| **Worker Recovery** | 100% | 100% | ✅ |

## 3. Bottlenecks & Findings
- **Database Contention:** During the 1,000 merchant burst, we observed minor locking contention on the `task_queue` table. The implementation of `SKIP LOCKED` significantly mitigated this.
- **AI Latency:** The primary bottleneck for end-to-end response time is the AI provider's latency. The async wrapper and circuit breaker ensure that AI slowness does not stall the entire worker pool.
- **Memory Usage:** Workers remained stable at ~150MB memory usage, even during high-concurrency processing.

## 4. Scaling Recommendations
- **Vertical Scaling:** For up to 5,000 active merchants, increasing the database CPU/Memory will suffice.
- **Horizontal Scaling:** For > 5,000 merchants, we recommend moving the `task_queue` to Redis and partitioning the `audit_logs` table.
