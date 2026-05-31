# SellMate AI Backend API Documentation

## Overview

SellMate AI is a **multi-tenant SaaS platform** for merchants to manage their Telegram-based e-commerce operations. The backend uses **ID-centric architecture** where each merchant has a unique `shop_id` that serves as the primary identifier for all operations.

## Architecture

### ID-Centric Design

Every merchant is assigned a **unique shop_id** (format: `SM-XXXXXX`) upon registration. This ID is:

- **Immutable**: Never changes after generation
- **Unique**: Guaranteed to be unique across the system
- **Primary Identifier**: Used for all database queries and API operations
- **Multi-tenant Isolator**: Ensures complete data isolation between merchants

### Database Scoping

All tables include `shop_id` column for efficient filtering:

```sql
-- Example: Get all orders for a specific merchant
SELECT * FROM orders WHERE shop_id = 'SM-7890AB'

-- Example: Get all products for a merchant
SELECT * FROM products WHERE shop_id = 'SM-7890AB'
```

## Authentication Flow

### 1. Registration (Step 1)

**Endpoint**: `POST /api/auth/register`

**Request**:
```json
{
  "shop_name": "Fashion Hub Myanmar",
  "owner_name": "John Doe",
  "phone": "+95912345678",
  "password": "secure_password",
  "category": "clothing"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Registration successful",
  "shop_id": "SM-7890AB",
  "business_id": 1,
  "shop_name": "Fashion Hub Myanmar",
  "owner_name": "John Doe",
  "phone": "+95912345678",
  "category": "clothing"
}
```

**Backend Actions**:
1. Generate unique `shop_id`
2. Hash password with salt
3. Store merchant in database
4. Return `shop_id` for future reference

### 2. Login

**Endpoint**: `POST /api/auth/login`

**Request**:
```json
{
  "phone": "+95912345678",
  "password": "secure_password"
}
```

**Response**:
```json
{
  "success": true,
  "message": "Login successful",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "shop_id": "SM-7890AB",
  "business_id": 1,
  "shop_name": "Fashion Hub Myanmar",
  "owner_name": "John Doe",
  "category": "clothing"
}
```

**Backend Actions**:
1. Verify phone and password
2. Create JWT token with `shop_id` and `business_id`
3. Return token for authenticated requests

### 3. Session Management

**Endpoint**: `GET /api/auth/me`

**Headers**:
```
Authorization: Bearer <jwt_token>
```

**Response**:
```json
{
  "id": 1,
  "shop_id": "SM-7890AB",
  "name": "Fashion Hub Myanmar",
  "owner_name": "John Doe",
  "phone": "+95912345678",
  "category": "clothing"
}
```

## API Endpoints

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new merchant |
| POST | `/api/auth/login` | Login with phone & password |
| GET | `/api/auth/me` | Get current merchant info |
| POST | `/api/auth/verify-token` | Verify JWT token validity |
| GET | `/api/auth/merchant/{shop_id}` | Get merchant by shop_id |

### Orders Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/orders` | List orders (scoped by shop_id) |
| POST | `/api/orders` | Create new order |
| GET | `/api/orders/{order_id}` | Get order details |
| PUT | `/api/orders/{order_id}` | Update order status |
| DELETE | `/api/orders/{order_id}` | Delete order |

### Products Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/products` | List products (scoped by shop_id) |
| POST | `/api/products` | Create new product |
| GET | `/api/products/{product_id}` | Get product details |
| PUT | `/api/products/{product_id}` | Update product |
| DELETE | `/api/products/{product_id}` | Delete product |

### Webhook Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook/{shop_id}` | Receive Telegram updates |
| POST | `/api/register-bot` | Register bot token |

## Database Schema

### businesses Table

```sql
CREATE TABLE businesses (
    id SERIAL PRIMARY KEY,
    shop_id VARCHAR(20) UNIQUE NOT NULL,  -- SM-XXXXXX
    name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    phone VARCHAR(20) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    tg_bot_token TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### orders Table (Scoped by shop_id)

```sql
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    chat_id BIGINT NOT NULL,
    customer_name TEXT,
    phone_no VARCHAR(20),
    items TEXT NOT NULL,  -- JSON
    total_price INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT NOW()
);
```

### products Table (Scoped by shop_id)

```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    shop_id VARCHAR(20) NOT NULL REFERENCES businesses(shop_id),
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    stock INTEGER DEFAULT 0,
    category TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## ID Isolation Security

### Query Filtering

All queries must include `shop_id` filter:

```python
# ✅ CORRECT: Scoped query
async with pool.acquire() as conn:
    orders = await conn.fetch(
        "SELECT * FROM orders WHERE shop_id = $1",
        current_merchant["shop_id"]
    )

# ❌ WRONG: Unscoped query (security risk)
async with pool.acquire() as conn:
    orders = await conn.fetch("SELECT * FROM orders")
```

### JWT Token Payload

Each JWT token includes `shop_id`:

```python
payload = {
    'shop_id': 'SM-7890AB',
    'business_id': 1,
    'phone': '+95912345678',
    'iat': datetime.utcnow(),
    'exp': datetime.utcnow() + timedelta(hours=24)
}
```

### Middleware Enforcement

All protected endpoints verify `shop_id` from token:

```python
@router.get("/api/orders")
async def get_orders(current_merchant = Depends(get_current_merchant)):
    # current_merchant["shop_id"] is guaranteed from JWT
    # All queries automatically scoped to this shop_id
    pass
```

## Integration with Landing Page & Dashboard

### Landing Page Integration

```javascript
// Landing page can display merchant info by shop_id
const response = await fetch('/api/auth/merchant/SM-7890AB');
const merchant = await response.json();
console.log(merchant.shop_name); // "Fashion Hub Myanmar"
```

### Dashboard Integration

```javascript
// Dashboard uses JWT token for all requests
const token = localStorage.getItem('auth_token');
const headers = {
    'Authorization': `Bearer ${token}`
};

// All requests automatically scoped to merchant's shop_id
const orders = await fetch('/api/orders', { headers });
```

## Environment Variables

```env
DATABASE_URL=postgresql://user:password@localhost:5432/sellmate_ai
JWT_SECRET=your-secret-key-change-in-production
JWT_EXPIRY_HOURS=24
GROQ_API_KEY=your-groq-api-key
LLAMA_API_KEY=your-llama-api-key
HOST=0.0.0.0
PORT=8000
DEBUG=False
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Database

```bash
createdb sellmate_ai
psql sellmate_ai < app/db/schema.sql
```

### 3. Set Environment Variables

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/sellmate_ai"
export JWT_SECRET="your-secret-key"
export GROQ_API_KEY="your-groq-api-key"
```

### 4. Run Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. Access API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Error Handling

### Standard Error Response

```json
{
  "detail": "Invalid phone or password"
}
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 500 | Internal Server Error |

## Security Best Practices

1. **Always use HTTPS** in production
2. **Rotate JWT_SECRET** regularly
3. **Hash passwords** with strong algorithms
4. **Validate shop_id** format before queries
5. **Log all authentication attempts**
6. **Implement rate limiting** on auth endpoints
7. **Use environment variables** for secrets
8. **Enable CORS** only for trusted domains

## Support

For issues or questions, contact: support@sellmate-ai.shop
