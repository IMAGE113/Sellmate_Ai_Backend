import re
from typing import Dict, Any, List, Tuple

class ValidationService:
    @staticmethod
    def validate_phone(phone: str) -> bool:
        if not phone:
            return False
        # Basic Myanmar phone validation (simplified)
        clean_phone = re.sub(r'[^0-9]', '', phone)
        return len(clean_phone) >= 7 and len(clean_phone) <= 12

    @staticmethod
    def validate_quantity(qty: Any) -> bool:
        try:
            val = int(qty)
            return val > 0
        except (ValueError, TypeError):
            return False

    @staticmethod
    def validate_extracted_data(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errors = []
        if data.get("phone_no") and not ValidationService.validate_phone(data["phone_no"]):
            errors.append("INVALID_PHONE")
        
        for item in data.get("items", []):
            if not ValidationService.validate_quantity(item.get("qty")):
                errors.append(f"INVALID_QUANTITY_{item.get('name')}")
        
        return len(errors) == 0, errors
