# SellMate AI: Multi-Tenant SaaS Telegram Bot Backend

This is a production-ready multi-tenant Telegram bot backend powered by Llama 3.3 (via Groq) that allows multiple merchants to have their own AI-powered ordering bots while sharing a central brain.

## Features

- **Multi-Tenancy:** Each merchant has their own Telegram Bot token and database segmentation.
- **Universal Llama Brain:** A single AI engine that dynamically switches context based on the merchant's business category (Clothing, Beauty, Cafe, etc.).
- **Dynamic Webhook Routing:** FastAPI handles webhooks for all bots via a single endpoint structure: `/webhook/{shop_id}`.
- **Robust Task Queue:** Uses an `asyncpg` task queue to handle incoming messages asynchronously, preventing bot crashes during heavy load.
- **Category-Specific Logic:** AI strictly asks for specific details (e.g., Size/Color for Clothing, Skin Type for Beauty) based on the shop's category.
- **Logistics Ready:** Database schema includes fields for future NJV logistics integration.

## Project Structure

```text
sellmate_ai/
├── app/
│   ├── api/
│   │   └── webhook.py      # Multi-tenant webhook handling
│   ├── core/
│   │   └── config.py       # Central configuration
│   ├── db/
│   │   └── database.py    # AsyncPG database pool and schema
│   ├── services/
│   │   ├── ai.py          # Universal Llama Brain logic
│   │   └── telegram.py    # Telegram API interaction
│   ├── workers/
│   │   └── order_worker.py # Background task processor
│   └── main.py            # FastAPI application entry point
├── requirements.txt       # Project dependencies
└── README.md              # Documentation
```

## Setup & Deployment

1.  **Database:** Ensure you have a PostgreSQL database available.
2.  **Environment Variables:** Set the following in your environment (e.g., Render, Heroku, or `.env`):
    - `DATABASE_URL`: Your PostgreSQL connection string.
    - `GROQ_API_KEY`: Your Groq API key for Llama access.
    - `DOMAIN`: Your application's domain (e.g., `api.sellmate-ai.shop`).
3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Run the Application:**
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000
    ```

## Registering a New Merchant

To register a new merchant and their bot:
1.  Use the `/register-bot` endpoint.
2.  Provide the `token`, `name`, and `category`.
3.  The system will automatically set the Telegram webhook for that bot.

## Category Logic

- **Clothing:** AI will strictly ask for "Size" and "Color".
- **Beauty:** AI will strictly ask for "Skin Type".
- **Cafe:** AI will strictly ask for "Sugar/Ice Level".
- **General:** Standard order extraction.

## Error Handling

- Strict `try-except` blocks around all database and AI operations.
- `callback_query_id` is always answered to prevent Telegram spinner timeouts.
- Task queue ensures that if the worker crashes, tasks are retried or logged.
