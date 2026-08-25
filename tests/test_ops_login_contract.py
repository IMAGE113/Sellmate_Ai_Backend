import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOpsLoginContract(unittest.IsolatedAsyncioTestCase):
    async def test_login_returns_phone_and_role_for_ops_console(self):
        from app.services.auth import AuthService

        conn = AsyncMock()
        conn.fetchrow.return_value = {
            'id': 9,
            'shop_id': 'SM-ADMINQA',
            'name': 'Ops QA',
            'owner_name': 'Ops Tester',
            'phone': '09900000000',
            'password_hash': 'hashed',
            'requirements_text': '',
            'status': 'ACTIVE',
        }
        conn.fetchval.return_value = 'SUPER_ADMIN'
        acquire = MagicMock()
        acquire.__aenter__ = AsyncMock(return_value=conn)
        acquire.__aexit__ = AsyncMock(return_value=None)
        pool = MagicMock()
        pool.acquire.return_value = acquire

        with patch.object(AuthService, 'verify_password', return_value=True), \
             patch.object(AuthService, 'create_jwt_token', return_value='qa-jwt'):
            success, response = await AuthService.login_merchant(pool, 'SM-ADMINQA', 'password')

        self.assertTrue(success)
        self.assertEqual(response['phone'], '09900000000')
        self.assertEqual(response['role'], 'SUPER_ADMIN')
        self.assertEqual(response['token'], 'qa-jwt')


if __name__ == '__main__':
    unittest.main()
