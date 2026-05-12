import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# Centralized Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DOMAIN = os.getenv("DOMAIN", "localhost")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set.")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY environment variable is not set.")
