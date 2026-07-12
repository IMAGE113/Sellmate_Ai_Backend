# System Function Map

This document outlines the critical functions within the Sellmate AI Backend for key operational areas: Order Workflow, Stock Deduction, Data Validation, and Webhook/API Handling.

## 1. Order Workflow

| Component | Critical Functions | Description |
|---|---|---|
| `app/workflow/flow_manager.py` | `get_next_step` | Determines the next step in the order processing flow based on intent and extracted data. |
| `app/services/order_service.py` | `get_or_create_active_order` | Retrieves an active order or creates a new one for a given chat. |
| `app/services/order_service.py` | `update_status` | Manages the state transitions of an order, ensuring valid status changes. |
| `app/workers/order_worker.py` | `run_worker` | The main loop for processing inbound messages and driving the order workflow. |

## 2. Stock Deduction

| Component | Critical Functions | Description |
|---|---|---|
| `app/db/database.py` | `ProductRepository.get_product_by_name` | Retrieves product details, including current stock, by product name. |
| `app/db/database.py` | `ProductRepository.update_product_stock` | Updates the stock level of a product after an order is confirmed or cancelled. |
| `app/workers/order_worker.py` | Stock deduction logic within `ORDER_CONFIRMED` block | Checks stock availability, deducts stock, and handles insufficient stock scenarios. |

## 3. Data Validation

| Component | Critical Functions | Description |
|---|---|---|
| `app/services/validation_service.py` | (All functions) | Provides various validation utilities for incoming data. |
| `app/services/ai.py` | `extract_data` | Extracts and structures data from user input using AI. |
| `app/services/ai.py` | `merge_data` | Merges newly extracted data with existing order data. |
| `app/workers/order_worker.py` | `make_json_safe` | Ensures Decimal types are converted to float for JSON serialization. |
| `app/workers/order_worker.py` | `force_dict` | Converts various data types to a dictionary, handling potential JSON parsing errors. |

## 4. Webhook/API Handling

| Component | Critical Functions | Description |
|---|---|---|
| `app/api/webhook.py` | `webhook_receiver` | The main entry point for incoming webhook messages, including Telegram updates. |
| `app/services/s3_service.py` | `upload_file` | Handles uploading files (e.g., payment screenshots) to S3. |
| `app/services/telegram_service.py` | `download_file` | Downloads files from Telegram servers. |
| `app/queue/queue_manager.py` | `push` | Adds incoming messages to the processing queue. |
| `app/queue/queue_manager.py` | `pop` | Retrieves messages from the processing queue for workers. |
