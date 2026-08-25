import importlib
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


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
        for quantity in (0, 1.5, float("nan"), float("inf"), True):
            self.assertFalse(await repo.deduct_stock_batch([(10, quantity)]))
            self.assertFalse(await repo.restore_stock_batch([(10, quantity)]))
        with self.assertRaises(ValueError):
            await repo.update_product_stock(10, 1.5)
        pool.acquire.assert_not_called()

    async def test_atomic_finalization_rejects_non_discrete_quantity_without_db_access(self):
        from app.db.database import OrderRepository

        pool = MagicMock()
        repo = OrderRepository(pool, "shop-a")
        for quantity in (1.5, float("nan"), float("inf"), True):
            self.assertFalse(
                await repo.finalize_order_with_inventory(
                    7, {"items": []}, "SM-ORD-000007", [(10, quantity)]
                )
            )
        pool.acquire.assert_not_called()

    def test_ai_drops_non_discrete_quantities(self):
        from app.services.ai import AI

        for quantity in (1.5, "NaN", "Infinity", "-Infinity"):
            normalized = AI().normalize_extracted_data(
                {"items": [{"name": "Widget", "qty": quantity}]}
            )
            self.assertEqual(normalized["items"], [])

    async def test_fresh_database_bootstrap_backfills_are_safe(self):
        from app.db import database

        conn = AsyncMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        with patch.object(database.os.path, "exists", return_value=True), patch.object(
            database, "open", mock_open(read_data="CREATE TABLE IF NOT EXISTS qa_marker(id int);")
        ):
            await database.init_db(pool)
        bootstrap_sql = conn.execute.await_args_list[0].args[0]
        self.assertIn("ALTER TABLE IF EXISTS products", bootstrap_sql)
        self.assertIn("ALTER TABLE IF EXISTS orders", bootstrap_sql)
        index_sql = "\n".join(call.args[0] for call in conn.execute.await_args_list)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS products_sku_key", index_sql)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS orders_order_number_key", index_sql)

    async def test_idempotency_queries_are_tenant_scoped(self):
        from app.services.idempotency_service import IdempotencyRepository

        repo = IdempotencyRepository(AsyncMock(), "shop-a")
        repo.fetch_one = AsyncMock(return_value=None)
        await repo.is_processed(123)
        await repo.atomic_check_and_mark(123)
        calls = repo.fetch_one.await_args_list
        self.assertIn("shop_id", calls[0].args[0])
        self.assertEqual(calls[0].args[1:], (123, "shop-a"))
        self.assertIn("ON CONFLICT (shop_id, update_id)", calls[1].args[0])

    def test_weak_jwt_secret_is_rejected_at_startup(self):
        import subprocess
        import sys

        env = os.environ.copy()
        env.update({
            "DATABASE_URL": "postgresql://qa:qa@127.0.0.1:5432/qa",
            "GROQ_API_KEY": "qa",
            "JWT_SECRET": "short",
            "PYTHONPATH": os.getcwd(),
        })
        result = subprocess.run(
            [sys.executable, "-c", "import app.core.config"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least 32 characters", result.stderr)

    def test_deployed_frontend_cors_origins_are_allowed_by_default(self):
        import subprocess
        import sys

        env = os.environ.copy()
        env.update({
            "DATABASE_URL": "postgresql://qa:qa@127.0.0.1:5432/qa",
            "GROQ_API_KEY": "qa",
            "JWT_SECRET": "qa-non-default-secret-0123456789abcdef",
            "PYTHONPATH": os.getcwd(),
        })
        env.pop("CORS_ORIGINS", None)
        result = subprocess.run(
            [sys.executable, "-c", "from app.core.config import CORS_ORIGINS; print('\\n'.join(CORS_ORIGINS))"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        origins = set(result.stdout.splitlines())
        self.assertTrue({
            "http://localhost:3000",
            "https://sellmate-merchant-dashboard.onrender.com",
            "https://sellmate-internal-ops-console.onrender.com",
            "https://sellmate-ai-landingpage.onrender.com",
        }.issubset(origins))

    def test_fractional_and_boolean_quantities_are_rejected(self):
        from app.services.validation_service import ValidationService

        self.assertFalse(ValidationService.validate_quantity(1.2))
        self.assertFalse(ValidationService.validate_quantity(True))
        self.assertTrue(ValidationService.validate_quantity(2))
        self.assertTrue(ValidationService.validate_quantity("2"))

    async def test_dashboard_rejects_nonfinite_prices(self):
        from app.api import dashboard_router

        pool = AsyncMock()
        with patch.object(dashboard_router, "get_db_pool", new=AsyncMock(return_value=pool)):
            for value in ("NaN", "Infinity", "-Infinity"):
                with self.assertRaises(Exception) as create_error:
                    await dashboard_router.create_product(
                        {"name": "Widget", "price": value, "stock": 1},
                        {"shop_id": "shop-a"},
                    )
                self.assertEqual(getattr(create_error.exception, "status_code", None), 400)
                with self.assertRaises(Exception) as update_error:
                    await dashboard_router.update_product(
                        1, {"price": value}, {"shop_id": "shop-a"}
                    )
                self.assertEqual(getattr(update_error.exception, "status_code", None), 400)
        pool.acquire.assert_not_called()

    async def test_dashboard_rejects_malformed_numeric_update(self):
        from app.api import dashboard_router

        with patch.object(dashboard_router, "get_db_pool", new=AsyncMock(return_value=AsyncMock())):
            with self.assertRaises(Exception) as raised:
                await dashboard_router.update_product(1, {"price": "not-a-number"}, {"shop_id": "shop-a"})
        self.assertEqual(getattr(raised.exception, "status_code", None), 400)

    async def test_dashboard_rejects_self_referential_variant(self):
        from app.api import dashboard_router

        with patch.object(dashboard_router, "get_db_pool", new=AsyncMock(return_value=AsyncMock())):
            with self.assertRaises(Exception) as raised:
                await dashboard_router.update_product(5, {"variant_of_id": 5}, {"shop_id": "shop-a"})
        self.assertEqual(getattr(raised.exception, "status_code", None), 400)

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

    async def test_dashboard_profile_matches_dashboard_contract_without_bot_token(self):
        from app.services.dashboard_service import DashboardRepository

        conn = AsyncMock()
        conn.fetchrow.return_value = {
            "id": 1,
            "shop_id": "shop-a",
            "name": "Shop A",
            "shop_name": "Shop A",
            "owner_name": "Owner A",
            "phone": "10000001",
            "requirements": "Deliver in Yangon",
            "category": None,
            "status": "ACTIVE",
            "workflow_config": None,
            "created_at": "2026-01-01T00:00:00Z",
        }
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        profile = await DashboardRepository(pool, "shop-a").get_merchant_profile()
        query = conn.fetchrow.await_args.args[0]
        self.assertIn("name AS shop_name", query)
        self.assertIn("requirements_text AS requirements", query)
        self.assertNotIn("tg_bot_token", query)
        self.assertEqual(profile["shop_name"], "Shop A")
        self.assertEqual(profile["requirements"], "Deliver in Yangon")
        self.assertNotIn("bot_token", profile)

    async def test_dashboard_settings_preserve_token_when_not_supplied(self):
        from app.services.dashboard_service import DashboardRepository

        conn = AsyncMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        await DashboardRepository(pool, "shop-a").update_merchant_settings({"name": "Updated"})
        query, *params = conn.execute.await_args.args
        self.assertNotIn("tg_bot_token", query)
        self.assertEqual(params, ["Updated", "shop-a"])

    async def test_dashboard_settings_reject_invalid_token(self):
        from app.services.dashboard_service import DashboardRepository

        with self.assertRaisesRegex(ValueError, "Invalid Telegram bot token format"):
            await DashboardRepository(MagicMock(), "shop-a").update_merchant_settings(
                {"bot_token": "not-a-telegram-token"}
            )

    async def test_webhook_spam_caches_are_bounded(self):
        from app.api import webhook

        webhook._recent_messages.clear()
        webhook._chat_message_windows.clear()
        try:
            for index in range(20000):
                webhook._is_duplicate_or_spam("shop-a", index, f"message-{index}")
            self.assertLessEqual(len(webhook._recent_messages), webhook._MAX_RECENT_KEYS)
            self.assertLessEqual(len(webhook._chat_message_windows), webhook._MAX_CHAT_WINDOWS)
        finally:
            webhook._recent_messages.clear()
            webhook._chat_message_windows.clear()

    async def test_lifespan_closes_global_http_clients(self):
        import app.main as main
        import app.services.ai as ai_module
        import app.services.telegram as telegram_module

        async def idle():
            await asyncio.Event().wait()

        pool = MagicMock()
        ai_close = AsyncMock()
        telegram_close = AsyncMock()
        with patch.object(main, "get_db_pool", new=AsyncMock(return_value=pool)), patch.object(
            main, "init_db", new=AsyncMock()
        ), patch.object(main, "close_db_pool", new=AsyncMock()), patch.object(
            main, "run_worker", new=idle
        ), patch.object(main, "run_notification_worker", new=idle), patch.object(
            main, "run_cleanup_worker", new=idle
        ), patch.object(ai_module.http_client, "aclose", new=ai_close), patch.object(
            telegram_module.http_client, "aclose", new=telegram_close
        ):
            context = main.lifespan(main.app)
            await context.__aenter__()
            await context.__aexit__(None, None, None)
        ai_close.assert_awaited_once()
        telegram_close.assert_awaited_once()

    async def test_notification_worker_claims_rows_atomically(self):
        import asyncio
        from app.workers import notification_worker

        conn = AsyncMock()
        conn.fetch.return_value = []
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        async def stop(_):
            raise asyncio.CancelledError()

        with patch.object(notification_worker, "get_db_pool", new=AsyncMock(return_value=pool)), patch.object(
            notification_worker.asyncio, "sleep", new=stop
        ):
            with self.assertRaises(asyncio.CancelledError):
                await notification_worker.run_notification_worker()
        query = conn.fetch.await_args.args[0]
        self.assertIn("FOR UPDATE SKIP LOCKED", query)
        self.assertIn("UPDATE notifications", query)

    async def test_recovery_validation_guards_malformed_order_ids(self):
        from app.services.recovery_validation import RecoveryValidationRepository

        conn = AsyncMock()
        conn.fetch.return_value = []
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        await RecoveryValidationRepository(pool, "SYSTEM").get_inconsistent_orders()
        query = conn.fetch.await_args.args[0]
        self.assertIn("~ '^[0-9]+$'", query)
        self.assertIn("ELSE NULL", query)

    async def test_rate_limiter_bounds_distinct_keys(self):
        from app.services.rate_limiter import RateLimiter

        limiter = RateLimiter()
        for index in range(limiter.MAX_KEYS + 100):
            limiter.check_limit(f"msg:{index}", 60, 60)
        self.assertLessEqual(len(limiter.limits), limiter.MAX_KEYS)
        allowed, remaining = limiter.check_limit("msg:stable", 2, 60)
        self.assertTrue(allowed)
        self.assertEqual(remaining, 1)
        allowed, remaining = limiter.check_limit("msg:stable", 2, 60)
        self.assertTrue(allowed)
        self.assertEqual(remaining, 0)
        allowed, remaining = limiter.check_limit("msg:stable", 2, 60)
        self.assertFalse(allowed)
        self.assertEqual(remaining, 0)

    async def test_dashboard_analytics_accepts_decimal_and_malformed_items(self):
        from app.services.dashboard_service import DashboardRepository

        conn = AsyncMock()
        conn.fetchrow.return_value = {"total_orders": 0, "top_selling_product": "Not Available"}
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        await DashboardRepository(pool, "shop-a").get_analytics()
        query = conn.fetchrow.await_args.args[0]
        self.assertIn("::numeric", query)
        self.assertIn("jsonb_typeof(extracted_data->'items')", query)

    async def test_order_finalization_failure_stays_inside_transaction(self):
        from app.db.database import OrderRepository

        conn = AsyncMock()
        conn.fetchrow.return_value = {"stock": 1}
        conn.execute.side_effect = ["UPDATE 1", RuntimeError("finalization failure")]
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=transaction)
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with self.assertRaisesRegex(RuntimeError, "finalization failure"):
            await OrderRepository(pool, "shop-a").finalize_order_with_inventory(
                7,
                {"items": [{"name": "Widget", "qty": 1}]},
                "SM-ORD-000007",
                [(10, 1)],
            )
        conn.transaction.assert_called_once_with()
        transaction.__aexit__.assert_awaited_once()

    async def test_worker_does_not_refail_stale_task_after_pop_failure(self):
        import asyncio
        from app.workers import order_worker

        pool = MagicMock()
        queue = MagicMock()
        queue.pop = AsyncMock(side_effect=[
            {"id": 77, "shop_id": "shop-a", "payload": "not-json"},
            RuntimeError("pop-db-down"),
        ])
        queue.fail = AsyncMock(return_value=None)
        monitor = MagicMock(run_recovery=AsyncMock(), heartbeat=AsyncMock())

        class StopWorker(Exception):
            pass

        sleeps = 0
        async def sleep(_):
            nonlocal sleeps
            sleeps += 1
            if sleeps >= 3:
                raise StopWorker()

        with patch.object(order_worker, "get_db_pool", new=AsyncMock(return_value=pool)), patch.object(
            order_worker, "QueueManager", return_value=queue
        ), patch.object(order_worker, "WorkerMonitor", return_value=monitor), patch.object(
            order_worker.asyncio, "sleep", new=sleep
        ):
            with self.assertRaises(StopWorker):
                await order_worker.run_worker()
        queue.fail.assert_awaited_once()

    async def test_worker_survives_queue_ack_failure(self):
        import asyncio
        from app.workers import order_worker

        pool = MagicMock()
        queue = MagicMock()
        queue.pop = AsyncMock(return_value={"id": 77, "shop_id": "shop-a", "payload": "not-json"})
        queue.fail = AsyncMock(side_effect=RuntimeError("ack-db-down"))
        monitor = MagicMock()
        monitor.run_recovery = AsyncMock()
        monitor.heartbeat = AsyncMock()

        class StopWorker(Exception):
            pass

        async def stop(_):
            raise StopWorker()

        with patch.object(order_worker, "get_db_pool", new=AsyncMock(return_value=pool)), patch.object(
            order_worker, "QueueManager", return_value=queue
        ), patch.object(order_worker, "WorkerMonitor", return_value=monitor), patch.object(
            order_worker.asyncio, "sleep", new=stop
        ):
            with self.assertRaises(StopWorker):
                await order_worker.run_worker()
        queue.fail.assert_awaited_once()

    async def test_worker_human_takeover_completes_without_unbound_flow(self):
        import json
        from app.workers import order_worker

        class StopWorker(Exception):
            pass

        pool = MagicMock()
        queue = MagicMock()
        queue.pop = AsyncMock(side_effect=[
            {"id": 77, "shop_id": "shop-a", "payload": json.dumps({"chat_id": 900, "data": {"user_text": "hello"}})},
            None,
        ])
        queue.complete = AsyncMock()
        queue.fail = AsyncMock()
        monitor = MagicMock(run_recovery=AsyncMock(), heartbeat=AsyncMock())
        merchant_repo = MagicMock()
        merchant_repo.get_merchant_by_shop_id = AsyncMock(return_value={
            "id": 1, "shop_id": "shop-a", "name": "Shop A", "tg_bot_token": "token",
            "status": "ACTIVE", "is_human_takeover_active": True,
        })
        lifecycle = MagicMock(validate_active=AsyncMock())
        lock = MagicMock(acquire=AsyncMock(return_value=True), release=AsyncMock())
        async def stop_sleep(_):
            raise StopWorker()

        with patch.object(order_worker, "get_db_pool", new=AsyncMock(return_value=pool)), \
             patch.object(order_worker, "WorkerMonitor", return_value=monitor), \
             patch.object(order_worker, "QueueManager", return_value=queue), \
             patch.object(order_worker, "MerchantRepository", return_value=merchant_repo), \
             patch.object(order_worker, "LifecycleService", return_value=lifecycle), \
             patch.object(order_worker, "LockManager", return_value=lock), \
             patch.object(order_worker, "send", new=AsyncMock()), \
             patch.object(order_worker.rate_limiter, "validate_merchant_message"), \
             patch.object(order_worker.rate_limiter, "validate_ai_usage"), \
             patch.object(order_worker.asyncio, "sleep", new=stop_sleep):
            with self.assertRaises(StopWorker):
                await order_worker.run_worker()

        queue.complete.assert_awaited_once_with(77)
        queue.fail.assert_not_awaited()
        lock.release.assert_awaited_once_with(900)

    async def test_auth_database_errors_return_generic_messages(self):
        from app.services.auth import AuthService

        class BrokenAcquire:
            async def __aenter__(self):
                raise RuntimeError("DB_SECRET_MARKER")
            async def __aexit__(self, *args):
                return None

        class BrokenPool:
            def acquire(self):
                return BrokenAcquire()

        success, response = await AuthService.login_merchant(BrokenPool(), "SM-ABC123", "password")
        self.assertFalse(success)
        self.assertEqual(response["error"], "Login failed")
        self.assertNotIn("DB_SECRET_MARKER", response["error"])

    async def test_auth_merchant_info_normalizes_nullable_legacy_fields(self):
        from app.services.auth import AuthService

        conn = AsyncMock()
        conn.fetchrow.return_value = {
            "id": 1,
            "shop_id": "shop-a",
            "name": "Shop A",
            "owner_name": None,
            "phone": None,
            "requirements_text": None,
        }
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        result = await AuthService.get_merchant_by_shop_id(pool, "shop-a")
        self.assertEqual(result["owner_name"], "")
        self.assertEqual(result["phone"], "")
        self.assertEqual(result["requirements"], "")

    async def test_oversized_bearer_token_is_rejected_before_db_access(self):
        from app.api import auth_router

        with self.assertRaises(Exception) as raised:
            await auth_router.get_current_merchant("Bearer " + ("x" * 4097))
        self.assertEqual(getattr(raised.exception, "status_code", None), 401)

    async def test_public_merchant_lookup_redacts_pii(self):
        from app.api import auth_router

        merchant = {
            "id": 1,
            "shop_id": "SM-PUBLIC",
            "name": "Public Shop",
            "owner_name": "Private Owner",
            "phone": "09999999999",
            "requirements": "Delivery details",
        }
        with patch.object(auth_router, "validate_shop_id", new=AsyncMock(return_value=True)), patch.object(
            auth_router, "get_db_pool", new=AsyncMock(return_value=AsyncMock())
        ), patch.object(auth_router, "get_business_by_shop_id", new=AsyncMock(return_value=merchant)):
            result = await auth_router.get_merchant_by_id("SM-PUBLIC")
        self.assertEqual(result["name"], "Public Shop")
        self.assertEqual(result["requirements"], "")
        self.assertEqual(result["owner_name"], "")
        self.assertEqual(result["phone"], "")

    async def test_jwt_identity_claims_must_match_database(self):
        import jwt
        from app.api import auth_router
        from app.core.config import JWT_SECRET

        token = jwt.encode(
            {"shop_id": "shop-a", "business_id": 999, "phone": "wrong", "iat": 0, "exp": 4102444800},
            JWT_SECRET,
            algorithm="HS256",
        )
        conn = AsyncMock()
        conn.fetchrow.return_value = {"id": 1, "phone": "10000001", "status": "ACTIVE"}
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire
        with patch.object(auth_router, "get_db_pool", new=AsyncMock(return_value=pool)):
            with self.assertRaises(Exception) as raised:
                await auth_router.get_current_merchant(f"Bearer {token}")
        self.assertEqual(getattr(raised.exception, "status_code", None), 401)

    async def test_malformed_signed_jwt_is_rejected(self):
        import jwt
        from app.api import auth_router
        from app.core.config import JWT_SECRET

        token = jwt.encode({"iat": 0, "exp": 4102444800}, JWT_SECRET, algorithm="HS256")
        pool = MagicMock()
        with patch.object(auth_router, "get_db_pool", new=AsyncMock(return_value=pool)):
            with self.assertRaises(Exception) as raised:
                await auth_router.get_current_merchant(f"Bearer {token}")
        self.assertEqual(getattr(raised.exception, "status_code", None), 401)
        pool.acquire.assert_not_called()

    async def test_webhook_security_requires_configured_signature(self):
        from app.core.security_webhook import WebhookSecurity

        request = MagicMock()
        request.headers = {}
        request.body = AsyncMock(return_value=b"payload")
        with self.assertRaises(Exception) as raised:
            await WebhookSecurity.validate_request(request, "secret")
        self.assertEqual(getattr(raised.exception, "status_code", None), 401)


    async def test_dashboard_products_include_inventory_metadata(self):
        from app.api import dashboard_router

        conn = AsyncMock()
        conn.fetch.return_value = [
            {
                "product_id": 7,
                "product_name": "Widget",
                "price": 12.5,
                "quantity": 4,
                "sku": "WIDGET-001",
                "variant_of_id": None,
                "attributes": "{}",
                "status": "active",
                "created_date": "2026-08-25T00:00:00",
            }
        ]
        pool = MagicMock()
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool.acquire.return_value = acquire

        with patch.object(dashboard_router, "get_db_pool", new=AsyncMock(return_value=pool)):
            result = await dashboard_router.get_products({"shop_id": "shop-a"})

        self.assertEqual(result[0]["sku"], "WIDGET-001")
        self.assertIsNone(result[0]["variant_of_id"])
        self.assertIn("sku, variant_of_id, attributes", conn.fetch.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
