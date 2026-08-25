import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from app.db.database import OrderRepository


class TestOrderDashboardProjection(unittest.IsolatedAsyncioTestCase):
    async def test_finalization_persists_dashboard_fields(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {"stock": 7}
        conn.execute.side_effect = ["UPDATE 1", "UPDATE 1", "INSERT 0 1"]
        transaction = MagicMock()
        transaction.__aenter__ = AsyncMock(return_value=None)
        transaction.__aexit__ = AsyncMock(return_value=None)
        conn.transaction = MagicMock(return_value=transaction)

        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        extracted = {
            "items": [{"name": "Integration QA Product", "qty": 1}],
            "customer_name": "Randy",
            "total_price": 12.5,
            "payment_method": "COD",
        }
        result = await OrderRepository(pool, "shop-a").finalize_order_with_inventory(
            29, extracted, "SM-ORD-TEST", [(5, 1)],
        )

        self.assertTrue(result)
        order_update = conn.execute.call_args_list[1]
        query = order_update.args[0]
        self.assertIn("customer_name = $2", query)
        self.assertIn("total_price = $3", query)
        self.assertEqual(order_update.args[2:7], ("Randy", 12.5, "SM-ORD-TEST", "Order confirmed: SM-ORD-TEST", 29))
        self.assertEqual(order_update.args[7], "shop-a")
        self.assertEqual(json.loads(order_update.args[1])["payment_method"], "COD")


if __name__ == "__main__":
    unittest.main()
