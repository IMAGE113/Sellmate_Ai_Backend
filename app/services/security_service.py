from typing import List
from app.db.database import BaseRepository
from app.core.errors import SellMateError

class PermissionDenied(SellMateError):
    pass

class SecurityRepository(BaseRepository):
    async def get_admin_permissions(self, admin_chat_id: int) -> List[str]:
        query = """
            SELECT r.permissions FROM merchant_admins ma
            JOIN roles r ON ma.role_id = r.id
            WHERE ma.admin_chat_id = $1 AND ma.shop_id = $2 AND ma.active_status = TRUE
        """
        row = await self.fetch_one(query, admin_chat_id, self.shop_id)
        return row['permissions'] if row else []

class SecurityService:
    def __init__(self, repo: SecurityRepository):
        self.repo = repo

    async def authorize(self, admin_chat_id: int, required_permission: str):
        permissions = await self.repo.get_admin_permissions(admin_chat_id)
        if "all" in permissions:
            return True
        if required_permission not in permissions:
            raise PermissionDenied(f"Admin {admin_chat_id} does not have {required_permission} permission")
        return True

    def validate_merchant_ownership(self, shop_id: str, resource_shop_id: str):
        if shop_id != resource_shop_id:
            raise PermissionDenied("Cross-tenant resource access attempt detected")
