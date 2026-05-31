import time
from typing import Dict, Tuple
from app.core.errors import SellMateError

class RateLimitExceeded(SellMateError):
    pass

class RateLimiter:
    """
    In-memory rate limiter (SaaS soft limits).
    For a distributed production environment, this should use Redis.
    """
    def __init__(self):
        self.limits = {} # {key: (count, reset_time)}

    def check_limit(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        if key not in self.limits:
            self.limits[key] = (1, now + window_seconds)
            return True, limit - 1

        count, reset_time = self.limits[key]
        if now > reset_time:
            self.limits[key] = (1, now + window_seconds)
            return True, limit - 1

        if count >= limit:
            return False, 0

        self.limits[key] = (count + 1, reset_time)
        return True, limit - (count + 1)

    def validate_merchant_message(self, shop_id: str):
        # 60 messages per minute per merchant
        allowed, remaining = self.check_limit(f"msg:{shop_id}", 60, 60)
        if not allowed:
            raise RateLimitExceeded(f"Merchant {shop_id} rate limit exceeded")

    def validate_ai_usage(self, shop_id: str):
        # 100 AI calls per hour per merchant
        allowed, remaining = self.check_limit(f"ai:{shop_id}", 100, 3600)
        if not allowed:
            raise RateLimitExceeded(f"Merchant {shop_id} AI usage limit exceeded")

rate_limiter = RateLimiter()
