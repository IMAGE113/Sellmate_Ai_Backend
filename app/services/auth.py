"""
Authentication Service for SellMate AI
Handles merchant registration, login, and session management
"""

import hashlib
import secrets
import asyncpg
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import jwt
from app.core.config import JWT_SECRET, JWT_EXPIRY_HOURS
from app.services.id_generator import generate_shop_id

class AuthService:
    """
    Handles merchant authentication and session management
    """
    
    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash password using SHA-256 with salt.
        
        Args:
            password: Plain text password
            
        Returns:
            str: Hashed password with salt
        """
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return f"{salt}${pwd_hash.hex()}"
    
    @staticmethod
    def verify_password(stored_hash: str, password: str) -> bool:
        """
        Verify password against stored hash.
        
        Args:
            stored_hash: Stored hashed password
            password: Plain text password to verify
            
        Returns:
            bool: True if password matches, False otherwise
        """
        try:
            salt, pwd_hash = stored_hash.split('$')
            new_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
            return new_hash.hex() == pwd_hash
        except Exception:
            return False
    
    @staticmethod
    def create_jwt_token(shop_id: str, business_id: int, phone: str, role: str = "ADMIN") -> str:
        """
        Create JWT token for authenticated session.
        
        Args:
            shop_id: Generated shop ID
            business_id: Database business ID
            phone: Merchant phone number
            role: User role (ADMIN, SUPER_ADMIN)
            
        Returns:
            str: JWT token
        """
        payload = {
            'shop_id': shop_id,
            'business_id': business_id,
            'phone': phone,
            'role': role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
        }
        return jwt.encode(payload, JWT_SECRET, algorithm='HS256')
    
    @staticmethod
    def verify_jwt_token(token: str) -> Optional[Dict]:
        """
        Verify and decode JWT token.
        
        Args:
            token: JWT token to verify
            
        Returns:
            dict: Token payload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    async def register_merchant(
        pool: asyncpg.Pool,
        shop_name: str,
        owner_name: str,
        phone: str,
        password: str,
        requirements: str = ""
    ) -> Tuple[bool, Dict]:
        """
        Register a new merchant with auto-generated shop_id.
        
        Args:
            pool: AsyncPG connection pool
            shop_name: Name of the shop
            owner_name: Owner's full name
            phone: Owner's phone number
            password: Login password
            requirements: Merchant custom requirements/instructions (raw text)
            
        Returns:
            tuple: (success: bool, response: dict)
        """
        try:
            # Generate unique shop_id
            shop_id = await generate_shop_id(pool)
            
            # Hash password
            password_hash = AuthService.hash_password(password)
            
            async with pool.acquire() as conn:
                # Check if phone already exists
                existing = await conn.fetchval(
                    "SELECT id FROM businesses WHERE phone = $1",
                    phone
                )
                
                if existing:
                    return False, {"error": "Phone number already registered"}
                
                # Insert new business
                row = await conn.fetchrow("""
                    INSERT INTO businesses 
                    (shop_id, name, owner_name, phone, password_hash, requirements_text, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    RETURNING id, shop_id, name, owner_name, phone, requirements_text
                """, shop_id, shop_name, owner_name, phone, password_hash, requirements)
                
                if row:
                    return True, {
                        "success": True,
                        "message": "Registration successful",
                        "shop_id": row["shop_id"],
                        "business_id": row["id"],
                        "shop_name": row["name"],
                        "owner_name": row["owner_name"],
                        "phone": row["phone"],
                        "requirements": row["requirements_text"] or ""
                    }
                else:
                    return False, {"error": "Failed to create business"}
                    
        except Exception as e:
            return False, {"error": f"Registration failed: {str(e)}"}
    
    @staticmethod
    async def login_merchant(
        pool: asyncpg.Pool,
        phone: str,
        password: str
    ) -> Tuple[bool, Dict]:
        """
        Authenticate merchant with phone and password.
        
        Args:
            pool: AsyncPG connection pool
            phone: Merchant phone number
            password: Login password
            
        Returns:
            tuple: (success: bool, response: dict)
        """
        try:
            async with pool.acquire() as conn:
                # Fetch merchant by phone
                business = await conn.fetchrow(
                    "SELECT id, shop_id, name, owner_name, phone, password_hash, requirements_text, status FROM businesses WHERE phone = $1",
                    phone
                )
                
                if not business:
                    return False, {"error": "Invalid phone or password"}
                
                if business["status"] == "SUSPENDED":
                    return False, {"error": "Account is suspended"}
                
                # Verify password
                if not AuthService.verify_password(business["password_hash"], password):
                    return False, {"error": "Invalid phone or password"}
                
                # Fetch role (default to ADMIN, check merchant_admins for SUPER_ADMIN)
                role = await conn.fetchval(
                    "SELECT role FROM merchant_admins WHERE shop_id = $1 AND active_status = TRUE",
                    business["shop_id"]
                ) or "ADMIN"

                # Create JWT token
                token = AuthService.create_jwt_token(
                    business["shop_id"],
                    business["id"],
                    business["phone"],
                    role=role
                )
                
                return True, {
                    "success": True,
                    "message": "Login successful",
                    "token": token,
                    "shop_id": business["shop_id"],
                    "business_id": business["id"],
                    "shop_name": business["name"],
                    "owner_name": business["owner_name"],
                    "requirements": business["requirements_text"] or ""
                }
                
        except Exception as e:
            return False, {"error": f"Login failed: {str(e)}"}
    
    @staticmethod
    async def get_merchant_by_shop_id(pool: asyncpg.Pool, shop_id: str) -> Optional[Dict]:
        """
        Retrieve merchant details by shop_id.
        
        Args:
            pool: AsyncPG connection pool
            shop_id: Shop ID
            
        Returns:
            dict: Merchant details or None if not found
        """
        try:
            async with pool.acquire() as conn:
                merchant = await conn.fetchrow(
                    "SELECT id, shop_id, name, owner_name, phone, requirements_text FROM businesses WHERE shop_id = $1",
                    shop_id
                )
                if merchant:
                    return {
                        "id": merchant["id"],
                        "shop_id": merchant["shop_id"],
                        "name": merchant["name"],
                        "owner_name": merchant["owner_name"],
                        "phone": merchant["phone"],
                        "requirements": merchant["requirements_text"] or ""
                    }
                return None
        except Exception:
            return None