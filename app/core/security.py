import re
import os
from typing import str

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent directory traversal."""
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9.-]', '_', filename)
    return filename

def validate_merchant_access(current_shop_id: str, target_shop_id: str):
    """Ensure merchant can only access their own data."""
    if current_shop_id != target_shop_id:
        from app.core.errors import MultiTenancyError
        raise MultiTenancyError("Access denied: Merchant isolation breach attempt.")
