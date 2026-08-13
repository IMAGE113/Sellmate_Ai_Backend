import re
import html
import unicodedata
from typing import Dict, Any, List, Tuple, Optional

class ValidationService:
    @staticmethod
    def normalize_unicode(text: str) -> str:
        """Normalize Unicode to NFC and handle basic Myanmar Zawgyi to Unicode if needed (simplified)."""
        if not text:
            return ""
        # Basic normalization
        text = unicodedata.normalize('NFC', text)
        # Note: Professional Zawgyi/Unicode conversion would require a dedicated library like 'myanmar-converter'
        # For now, we ensure NFC normalization.
        return text

    @staticmethod
    def validate_name(name: str) -> Tuple[bool, str]:
        """BUG-01, BUG-02: Validate customer name."""
        if not name:
            return False, ""
        
        name = name.strip()
        if not name:
            return False, ""
        
        # Length limits (BUG-09)
        if len(name) < 2:
            return False, name
        if len(name) > 60:
            return False, name[:60]
            
        # Reject obvious garbage (pure symbols/digits/emoji)
        # We allow Burmese characters, English letters, and spaces.
        # Burmese range: \u1000-\u109F
        if not re.search(r'[a-zA-Z\u1000-\u109F]', name):
            return False, name
            
        return True, name

    @staticmethod
    def validate_phone(phone: str) -> Tuple[bool, str]:
        """BUG-04, BUG-05: Validate and normalize Myanmar phone numbers."""
        if not phone:
            return False, ""
            
        # Convert Myanmar digits to ASCII
        my_digits = "၀၁၂၃၄၅၆၇၈၉"
        en_digits = "0123456789"
        digit_map = str.maketrans(my_digits, en_digits)
        phone = phone.translate(digit_map)
        
        # Strip all non-numeric
        clean_phone = re.sub(r'[^0-9]', '', phone)
        
        # Normalize +959 / 959 to 09
        if clean_phone.startswith('959'):
            clean_phone = '09' + clean_phone[3:]
        elif clean_phone.startswith('00959'):
            clean_phone = '09' + clean_phone[5:]
            
        # Myanmar mobile numbers are usually 09 + 7 to 9 digits
        if re.match(r'^09\d{7,9}$', clean_phone):
            return True, clean_phone
            
        return False, clean_phone

    @staticmethod
    def validate_address(address: str) -> Tuple[bool, str]:
        """BUG-06: Validate delivery address."""
        if not address:
            return False, ""
            
        address = address.strip()
        if not address:
            return False, ""
            
        # Length limits (BUG-09)
        if len(address) < 5: # "Yangon" is 6, so at least some detail
            return False, address
        if len(address) > 500:
            return False, address[:500]
            
        # Heuristic: should contain at least one letter or Burmese character
        if not re.search(r'[a-zA-Z\u1000-\u109F]', address):
            return False, address
            
        return True, address

    @staticmethod
    def validate_township(township: str, supported_townships: Optional[List[str]] = None) -> Tuple[bool, str]:
        """BUG-10: Validate township against supported list if available."""
        if not township:
            return False, ""
            
        township = township.strip()
        if not township:
            return False, ""
            
        if not supported_townships:
            # If no list provided, we just do basic string validation
            return len(township) >= 2, township
            
        # Case-insensitive, normalized matching
        norm_township = ValidationService.normalize_unicode(township).lower()
        for supported in supported_townships:
            if norm_township == ValidationService.normalize_unicode(supported).lower():
                return True, supported # Return the canonical name from the list
                
        return False, township

    @staticmethod
    def escape_html(text: str) -> str:
        """BUG-08: Escape text for Telegram HTML parse_mode."""
        if not text:
            return ""
        return html.escape(text)

    @staticmethod
    def validate_quantity(qty: Any) -> bool:
        try:
            val = int(qty)
            return val > 0
        except (ValueError, TypeError):
            return False

    @staticmethod
    def validate_extracted_data(data: Dict[str, Any], supported_townships: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
        errors = []
        
        if data.get("customer_name"):
            valid, _ = ValidationService.validate_name(data["customer_name"])
            if not valid: errors.append("INVALID_NAME")
            
        if data.get("phone_no"):
            valid, _ = ValidationService.validate_phone(data["phone_no"])
            if not valid: errors.append("INVALID_PHONE")
            
        if data.get("address"):
            valid, _ = ValidationService.validate_address(data["address"])
            if not valid: errors.append("INVALID_ADDRESS")
            
        if data.get("township"):
            valid, _ = ValidationService.validate_township(data["township"], supported_townships)
            if not valid: errors.append("INVALID_TOWNSHIP")
        
        for item in data.get("items", []):
            if not ValidationService.validate_quantity(item.get("qty")):
                errors.append(f"INVALID_QUANTITY_{item.get('name')}")
        
        return len(errors) == 0, errors
