import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# Centralized Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DOMAIN = os.getenv("DOMAIN", "localhost")

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", "24"))

# Server Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Telegram Configuration
TELEGRAM_API_BASE = "https://api.telegram.org"

# Llama AI Configuration
LLAMA_API_KEY = os.getenv("LLAMA_API_KEY", "")
LLAMA_API_URL = os.getenv("LLAMA_API_URL", "https://api.llama.ai")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set.")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is not set.")
