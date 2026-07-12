import httpx
import logging
import os

class TelegramService:
    def __init__(self):
        self.base_file_url = "https://api.telegram.org/file/bot"

    async def get_file_path(self, bot_token: str, file_id: str) -> str:
        url = f"https://api.telegram.org/bot{bot_token}/getFile"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params={
                "file_id": file_id
            })
            response.raise_for_status()
            file_info = response.json()["result"]
            return file_info["file_path"]

    async def download_file(self, bot_token: str, file_path: str) -> bytes:
        url = f"{self.base_file_url}{bot_token}/{file_path}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

telegram_service = TelegramService()
