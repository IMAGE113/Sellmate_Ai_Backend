import hmac
import hashlib
import time
from fastapi import Request, HTTPException
from app.core.errors import SellMateError

class WebhookSecurity:
    """
    Secures webhook endpoints with signature verification and replay attack protection.
    """
    
    @staticmethod
    def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
        if not signature or not secret:
            return False
        expected_signature = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature)

    @staticmethod
    async def validate_request(request: Request, secret: str):
        # 1. Signature Verification (if provided by platform)
        signature = request.headers.get("X-SellMate-Signature")
        body = await request.body()
        
        if signature and not WebhookSecurity.verify_signature(body, signature, secret):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # 2. Replay Attack Prevention (Timestamp check)
        timestamp = request.headers.get("X-SellMate-Timestamp")
        if timestamp:
            try:
                if abs(time.time() - int(timestamp)) > 300: # 5 minute window
                    raise HTTPException(status_code=401, detail="Request expired")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid timestamp")

        # 3. Request Hashing for Idempotency (Already handled in webhook service)
        return True
