"""
Authentication Router for SellMate AI
Handles registration, login, and merchant management
Uses 'requirements' (raw text instructions) instead of 'category'
"""

import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.db.database import get_db_pool
from app.services.auth import AuthService
from app.services.id_generator import validate_shop_id, get_business_by_shop_id

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Request/Response Models
class RegisterRequest(BaseModel):
    shop_name: str = Field(..., min_length=1, max_length=100)
    owner_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=10, max_length=20)
    password: str = Field(..., min_length=6, max_length=100)
    requirements: str = Field(default="", description="Raw text merchant custom requirements/instructions")

class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20)
    password: str = Field(..., min_length=6)

class RegisterResponse(BaseModel):
    success: bool
    message: str
    shop_id: str
    business_id: int
    shop_name: str
    owner_name: str
    phone: str
    requirements: str

class LoginResponse(BaseModel):
    success: bool
    message: str
    token: str
    shop_id: str
    business_id: int
    shop_name: str
    owner_name: str
    requirements: str

class MerchantInfo(BaseModel):
    id: int
    shop_id: str
    name: str
    owner_name: str
    phone: str
    requirements: str

# Dependency to get current merchant from token
async def get_current_merchant(authorization: Optional[str] = Header(None)):
    """
    Extract and verify JWT token from Authorization header.
    Format: Bearer <token>
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authorization scheme")
        
        payload = AuthService.verify_jwt_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        return payload
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest):
    """
    Register a new merchant with auto-generated shop_id.
    
    Step 1: User submits shop details including custom requirements
    Backend: Generates unique shop_id and stores merchant with requirements
    Response: Returns shop_id for future login
    """
    try:
        pool = await get_db_pool()
        success, response = await AuthService.register_merchant(
            pool,
            request.shop_name,
            request.owner_name,
            request.phone,
            request.password,
            requirements=request.requirements
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=response.get("error", "Registration failed"))
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Registration error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login merchant with phone and password.
    Returns JWT token for authenticated requests.
    """
    try:
        pool = await get_db_pool()
        success, response = await AuthService.login_merchant(
            pool,
            request.phone,
            request.password
        )
        
        if not success:
            raise HTTPException(status_code=401, detail=response.get("error", "Login failed"))
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/me", response_model=MerchantInfo)
async def get_current_merchant_info(current_merchant = Depends(get_current_merchant)):
    """
    Get current merchant information from JWT token.
    """
    try:
        pool = await get_db_pool()
        merchant = await AuthService.get_merchant_by_shop_id(pool, current_merchant["shop_id"])
        
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        
        return merchant
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Get merchant error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/verify-token")
async def verify_token(current_merchant = Depends(get_current_merchant)):
    """
    Verify if JWT token is still valid.
    Used by frontend to check session status.
    """
    return {
        "valid": True,
        "shop_id": current_merchant["shop_id"],
        "business_id": current_merchant["business_id"],
        "phone": current_merchant["phone"]
    }

@router.get("/merchant/{shop_id}", response_model=MerchantInfo)
async def get_merchant_by_id(shop_id: str):
    """
    Get merchant details by shop_id.
    Public endpoint for dashboard/landing page integration.
    """
    try:
        if not await validate_shop_id(shop_id):
            raise HTTPException(status_code=400, detail="Invalid shop_id format")
        
        pool = await get_db_pool()
        merchant = await get_business_by_shop_id(pool, shop_id)
        
        if not merchant:
            raise HTTPException(status_code=404, detail="Merchant not found")
        
        return {
            "id": merchant["id"],
            "shop_id": merchant["shop_id"],
            "name": merchant["name"],
            "owner_name": merchant["owner_name"],
            "phone": merchant["phone"],
            "requirements": merchant.get("requirements", "")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Get merchant error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/merchant/requirements/{shop_id}")
async def update_merchant_requirements(shop_id: str, requirements: str, current_merchant = Depends(get_current_merchant)):
    """
    Update merchant custom requirements.
    Only the merchant owner can update their own requirements.
    """
    try:
        # Verify ownership
        if current_merchant["shop_id"] != shop_id:
            raise HTTPException(status_code=403, detail="Unauthorized")
        
        if not await validate_shop_id(shop_id):
            raise HTTPException(status_code=400, detail="Invalid shop_id format")
        
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE businesses SET requirements=$1 WHERE shop_id=$2",
                requirements, shop_id
            )
        
        return {
            "success": True,
            "message": "Requirements updated successfully",
            "shop_id": shop_id,
            "requirements": requirements
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Update requirements error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")
