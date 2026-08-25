import unittest
from unittest.mock import AsyncMock


class TestOpsProjectionContract(unittest.IsolatedAsyncioTestCase):
    async def test_system_stats_query_returns_active_and_suspended_counts(self):
        from app.api.ops_router import OpsRepository

        repo = OpsRepository(None, 'SYSTEM')
        repo.fetch_one = AsyncMock(return_value={
            'total_merchants': 9,
            'active_merchants': 8,
            'suspended_merchants': 1,
            'total_orders': 33,
            'pending_tasks': 0,
            'failed_tasks': 0,
        })

        result = await repo.get_system_stats()
        query = repo.fetch_one.await_args.args[0]

        self.assertEqual(result['active_merchants'], 8)
        self.assertEqual(result['suspended_merchants'], 1)
        self.assertIn("status = 'ACTIVE'", query)
        self.assertIn("status = 'SUSPENDED'", query)

    async def test_merchant_list_query_projects_requirements(self):
        from app.api.ops_router import OpsRepository

        repo = OpsRepository(None, 'SYSTEM')
        repo.fetch_all = AsyncMock(return_value=[])

        await repo.get_all_merchants()
        query = repo.fetch_all.await_args.args[0]

        self.assertIn('requirements_text AS requirements', query)


if __name__ == '__main__':
    unittest.main()
