import importlib
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFullAuditFixes(unittest.IsolatedAsyncioTestCase):
    async def test_dead_letter_queries_are_parameterized_and_tenant_scoped(self):
        from app.services.dead_letter_service import DeadLetterRepository

        repo = DeadLetterRepository(AsyncMock(), "shop-a")
        repo.fetch_all = AsyncMock(return_value=[])
        await repo.list_dead_jobs("inbound_messages")
        repo.fetch_all.assert_awaited_once_with(
            "SELECT * FROM task_queue WHERE status = 'dead_letter' AND shop_id = $1 AND queue_name = $2",
            "shop-a",
            "inbound_messages",
        )

    async def test_dead_letter_mutations_are_tenant_scoped(self):
        from app.services.dead_letter_service import DeadLetterRepository

        repo = DeadLetterRepository(AsyncMock(), "shop-a")
        repo.execute = AsyncMock()
        await repo.retry_job(7)
        await repo.archive_job(8)
        self.assertEqual(repo.execute.await_args_list[0].args[1:], (7, "shop-a"))
        self.assertEqual(repo.execute.await_args_list[1].args[1:], (8, "shop-a"))

    async def test_duplicate_inventory_ids_are_aggregated_before_deduction(self):
        from app.db.database import ProductRepository

        conn = AsyncMock()
        conn.fetchrow.return_value = {"stock": 5}
        pool = MagicMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = acquire
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=transaction)

        repo = ProductRepository(pool, "shop-a")
        self.assertTrue(await repo.deduct_stock_batch([(10, 2), (10, 3)]))
        update_calls = [call for call in conn.execute.await_args_list if "stock = stock -" in call.args[0]]
        self.assertEqual(len(update_calls), 1)
        self.assertEqual(update_calls[0].args[1], 5.0)

    async def test_invalid_inventory_quantity_is_rejected_without_db_access(self):
        from app.db.database import ProductRepository

        pool = MagicMock()
        repo = ProductRepository(pool, "shop-a")
        self.assertFalse(await repo.deduct_stock_batch([(10, 0)]))
        pool.acquire.assert_not_called()

    async def test_notification_delivery_reports_telegram_failure(self):
        from app.workers.notification_worker import send_telegram_message

        response = MagicMock(status_code=429)
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)
        with patch("app.workers.notification_worker.httpx.AsyncClient", return_value=client):
            self.assertFalse(await send_telegram_message("token", 1, "hello"))

    async def test_notification_delivery_reports_telegram_success(self):
        from app.workers.notification_worker import send_telegram_message

        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": True}
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)
        with patch("app.workers.notification_worker.httpx.AsyncClient", return_value=client):
            self.assertTrue(await send_telegram_message("token", 1, "hello"))

    def test_dashboard_module_imports_json(self):
        module = importlib.import_module("app.api.dashboard_router")
        self.assertTrue(hasattr(module, "json"))

    async def test_webhook_security_requires_configured_signature(self):
        from app.core.security_webhook import WebhookSecurity

        request = MagicMock()
        request.headers = {}
        request.body = AsyncMock(return_value=b"payload")
        with self.assertRaises(Exception) as raised:
            await WebhookSecurity.validate_request(request, "secret")
        self.assertEqual(getattr(raised.exception, "status_code", None), 401)


if __name__ == "__main__":
    unittest.main()
