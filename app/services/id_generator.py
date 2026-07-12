"""
ID Generator Service for SellMate AI
Generates unique shop IDs with prefix (e.g., SM-7890)
"""

import random
import string
import asyncpg
from typing import Optional
from app.core.config import DATABASE_URL

class IDGenerator:
    """
    Generates unique shop IDs with the format: SM-XXXX
    where XXXX is a random alphanumeric string
    """
    
    PREFIX = "SM"
    ID_LENGTH = 6  # Total length after prefix (e.g., SM-ABC123)
    
    @staticmethod
    async def generate_unique_shop_id(pool: asyncpg.Pool) -> str:
        """
        Generate a unique shop ID that doesn't exist in the database.
        Format: SM-XXXXXX (where X is alphanumeric)
        
        Args:
            pool: AsyncPG connection pool
            
        Returns:
            str: Unique shop ID (e.g., "SM-7890AB")
        """
        max_attempts = 100
        
        for attempt in range(max_attempts):
            # Generate random alphanumeric string
            random_part = ''.join(
                random.choices(string.ascii_uppercase + string.digits, k=IDGenerator.ID_LENGTH)
            )
            shop_id = f"{IDGenerator.PREFIX}-{random_part}"
            
            # Check if this ID already exists
            async with pool.acquire() as conn:
                existing = await conn.fetchval(
                    "SELECT id FROM businesses WHERE shop_id = $1",
                    shop_id
                )
                
                if not existing:
                    return shop_id
        
        # Fallback: use timestamp-based ID if random generation fails
        import time
        timestamp_id = f"{IDGenerator.PREFIX}-{int(time.time() * 1000) % 1000000:06d}"
        return timestamp_id
    
    @staticmethod
    async def validate_shop_id(shop_id: str) -> bool:
        """
        Validate shop ID format.
        
        Args:
            shop_id: Shop ID to validate
            
        Returns:
            bool: True if valid format, False otherwise
        """
        if not shop_id or not isinstance(shop_id, str):
            return False
        
        parts = shop_id.split('-')
        if len(parts) != 2:
            return False
        
        if parts[0] != IDGenerator.PREFIX:
            return False
        
        if len(parts[1]) != IDGenerator.ID_LENGTH:
            return False
        
        if not all(c.isalnum() for c in parts[1]):
            return False
        
        return True
    
    @staticmethod
    async def get_business_by_shop_id(pool: asyncpg.Pool, shop_id: str) -> Optional[dict]:
        """
        Retrieve business details by shop_id.
        
        Args:
            pool: AsyncPG connection pool
            shop_id: Shop ID to look up
            
        Returns:
            dict: Business details or None if not found
        """
        if not await IDGenerator.validate_shop_id(shop_id):
            return None
        
        async with pool.acquire() as conn:
            business = await conn.fetchrow(
                "SELECT * FROM businesses WHERE shop_id = $1",
                shop_id
            )
            return dict(business) if business else None


# Singleton instance
_id_generator = IDGenerator()

async def generate_shop_id(pool: asyncpg.Pool) -> str:
    """Helper function to generate unique shop ID"""
    return await _id_generator.generate_unique_shop_id(pool)

async def validate_shop_id(shop_id: str) -> bool:
    """Helper function to validate shop ID format"""
    return await _id_generator.validate_shop_id(shop_id)

async def get_business_by_shop_id(pool: asyncpg.Pool, shop_id: str) -> Optional[dict]:
    """Helper function to get business by shop ID"""
    return await _id_generator.get_business_by_shop_id(pool, shop_id)
