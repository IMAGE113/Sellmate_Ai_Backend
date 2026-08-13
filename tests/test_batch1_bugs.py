import unittest
import html
from app.services.validation_service import ValidationService

class TestBatch1Bugs(unittest.TestCase):

    # BUG-01, BUG-02: Name Validation
    def test_name_validation(self):
        # Empty/Whitespace
        self.assertFalse(ValidationService.validate_name("")[0])
        self.assertFalse(ValidationService.validate_name("   ")[0])
        
        # Too short/long
        self.assertFalse(ValidationService.validate_name("A")[0])
        self.assertFalse(ValidationService.validate_name("a" * 61)[0])
        
        # Pure symbols/digits/emoji
        self.assertFalse(ValidationService.validate_name("12345")[0])
        self.assertFalse(ValidationService.validate_name("!!!@@@")[0])
        self.assertFalse(ValidationService.validate_name("😂😂😂")[0])
        
        # Valid names (English & Burmese)
        self.assertTrue(ValidationService.validate_name("John Doe")[0])
        self.assertTrue(ValidationService.validate_name("မောင်မောင်")[0])
        self.assertTrue(ValidationService.validate_name("John မောင်မောင်")[0])
        
        # Normalization (strip)
        valid, norm = ValidationService.validate_name("  John Doe  ")
        self.assertTrue(valid)
        self.assertEqual(norm, "John Doe")

    # BUG-04, BUG-05: Phone Validation
    def test_phone_validation(self):
        # Valid Myanmar formats
        self.assertTrue(ValidationService.validate_phone("09123456789")[0])
        self.assertEqual(ValidationService.validate_phone("+959123456789")[1], "09123456789")
        self.assertEqual(ValidationService.validate_phone("959123456789")[1], "09123456789")
        self.assertEqual(ValidationService.validate_phone("00959123456789")[1], "09123456789")
        
        # Myanmar digits
        self.assertEqual(ValidationService.validate_phone("၀၉၁၂၃၄၅၆၇၈၉")[1], "09123456789")
        
        # Invalid
        self.assertFalse(ValidationService.validate_phone("123")[0])
        self.assertFalse(ValidationService.validate_phone("0912345")[0]) # Too short
        self.assertFalse(ValidationService.validate_phone("abcdefghijk")[0])
        self.assertFalse(ValidationService.validate_phone("09123456789012")[0]) # Too long

    # BUG-06: Address Validation
    def test_address_validation(self):
        # Empty/Short
        self.assertFalse(ValidationService.validate_address("")[0])
        self.assertFalse(ValidationService.validate_address("Yang")[0])
        
        # Garbage
        self.assertFalse(ValidationService.validate_address("12345")[0]) # Pure digits
        self.assertFalse(ValidationService.validate_address("📍📍📍")[0]) # Pure emoji
        
        # Valid
        self.assertTrue(ValidationService.validate_address("No. 123, Pyay Road, Yangon")[0])
        self.assertTrue(ValidationService.validate_address("ရန်ကုန်၊ အမှတ် ၁၂၃")[0])

    # BUG-08: HTML Safety
    def test_html_safety(self):
        self.assertEqual(ValidationService.escape_html("<b>Test</b>"), "&lt;b&gt;Test&lt;/b&gt;")
        self.assertEqual(ValidationService.escape_html("A & B"), "A &amp; B")
        self.assertEqual(ValidationService.escape_html("<script>alert(1)</script>"), "&lt;script&gt;alert(1)&lt;/script&gt;")

    # BUG-10: Township Validation
    def test_township_validation(self):
        supported = ["Yangon", "Mandalay", "Naypyidaw"]
        
        # Valid
        self.assertTrue(ValidationService.validate_township("Yangon", supported)[0])
        self.assertTrue(ValidationService.validate_township("yangon", supported)[0]) # Case insensitive
        
        # Invalid
        self.assertFalse(ValidationService.validate_township("Narnia", supported)[0])
        
        # No list (basic check)
        self.assertTrue(ValidationService.validate_township("Anytown")[0])

    # BUG-11: Unicode Normalization
    def test_unicode_normalization(self):
        # Visually identical but different bytes (e.g., combining characters)
        text = "မင်္ဂလာပါ" # This is a standard string
        norm = ValidationService.normalize_unicode(text)
        self.assertEqual(text, norm)

if __name__ == "__main__":
    unittest.main()
