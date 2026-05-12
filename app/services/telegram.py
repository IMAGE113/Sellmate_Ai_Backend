import httpx
import logging

http_client = httpx.AsyncClient(timeout=10.0)

async def send(token: str, chat_id: int, text: str, reply_markup: dict = None):
    """
    Sends a message to a Telegram chat.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = await http_client.post(url, json=payload)
        if response.status_code != 200:
            logging.error(f"Telegram API Error: {response.status_code} - {response.text}")
        return response.json()
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")
        return None
