import ast
import inspect
import unittest
from unittest.mock import AsyncMock

from app.db.database import ProductRepository
from app.workers import order_worker


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, stocks):
        self.stocks = dict(stocks)
        self.selects = []
        self.updates = []

    def transaction(self):
        return FakeTransaction()

    async def fetchrow(self, query, *args):
        if query.lstrip().startswith("SELECT stock"):
            product_id, shop_id = args
            self.selects.append((product_id, shop_id))
            stock = self.stocks.get(product_id)
            return {"stock": stock} if stock is not None else None
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def execute(self, query, *args):
        product_id, shop_id = args[1], args[2]
        quantity = args[0]
        self.updates.append((product_id, quantity, shop_id))
        self.stocks[product_id] -= quantity


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return FakeAcquire(self.connection)


class TestBatch4Inventory(unittest.IsolatedAsyncioTestCase):
    async def test_variant_lookup_includes_name_and_attributes(self):
        repo = ProductRepository(AsyncMock(), "shop-1")
        repo.fetch_one = AsyncMock(return_value=None)

        await repo.get_product_variant(" Shirt ", {"size": "L", "color": "Red"})

        query, product_name, shop_id, attributes = repo.fetch_one.call_args.args
        self.assertIn("JOIN products p", query)
        self.assertIn("v.attributes @> $3::jsonb", query)
        self.assertEqual((product_name, shop_id), (" Shirt ", "shop-1"))
        self.assertIn('"size": "L"', attributes)
        self.assertIn('"color": "Red"', attributes)

    async def test_atomic_batch_deduction_refuses_oversell_without_updates(self):
        connection = FakeConnection({1: 2, 2: 10})
        repo = ProductRepository(FakePool(connection), "shop-1")

        result = await repo.deduct_stock_batch([(1, 3), (2, 1)])

        self.assertFalse(result)
        self.assertEqual(connection.updates, [])
        self.assertEqual(connection.stocks, {1: 2, 2: 10})

    async def test_atomic_batch_deduction_updates_each_resolved_product_once(self):
        connection = FakeConnection({1: 5, 2: 10})
        repo = ProductRepository(FakePool(connection), "shop-1")

        result = await repo.deduct_stock_batch([(1, 3), (2, 2)])

        self.assertTrue(result)
        self.assertEqual(connection.updates, [(1, 3, "shop-1"), (2, 2, "shop-1")])
        self.assertEqual(connection.stocks, {1: 2, 2: 8})

    def test_worker_uses_variant_lookup_without_name_fallback_when_attributes_exist(self):
        source = inspect.getsource(order_worker.run_worker)
        tree = ast.parse(source)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get_product_variant", "get_product_by_name"}
        ]
        variant_calls = [node for node in calls if node.func.attr == "get_product_variant"]
        self.assertTrue(variant_calls)
        self.assertTrue(any(isinstance(node.args[1], ast.Name) and node.args[1].id == "attributes" for node in variant_calls))
        self.assertIn("if attributes:", source)
        self.assertNotIn("if not p:\n                                    # Fallback to parent product", source)

    def test_worker_aggregates_duplicate_product_quantities(self):
        source = inspect.getsource(order_worker.run_worker)
        self.assertIn("deductions_by_product[p[\"id\"]] = deductions_by_product.get(p[\"id\"], 0) + qty", source)
        self.assertIn("p[\"stock\"] < deductions_by_product[p[\"id\"]]", source)

    def test_worker_rejects_invalid_quantities_as_out_of_stock(self):
        source = inspect.getsource(order_worker.run_worker)
        self.assertIn("except (TypeError, ValueError):", source)
        self.assertIn("if not p_name or qty <= 0:", source)
        self.assertIn('status_key = "OUT_OF_STOCK"', source)


if __name__ == "__main__":
    unittest.main()

