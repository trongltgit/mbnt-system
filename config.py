import os
from dotenv import load_dotenv

load_dotenv()

# Database Configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/mbnt_db"
)

# JWT Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

# App Configuration
APP_NAME = "MBNT System - GIAO DỊCH MUA BÁN NGOẠI TỆ NỘI BỘ"
APP_VERSION = "1.0.0"
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Default password
DEFAULT_PASSWORD = "Vcb@1234"

# Password requirements
MIN_PASSWORD_LENGTH = 8
PASSWORD_REGEX = r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"

# Upload configuration
UPLOAD_DIR = "uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv", "pdf"}

# Currencies
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "AUD", "SGD", "THB", "CAD", "CHF", "HKD", "DKK", "KRW", "NOK", "SEK", "VND"]

# Departments
DEPARTMENTS = {
    "K1": "KHDN1",
    "L1": "KHBL1",
    "TĐT": "PGD TĐT",
    "TN": "DV KHTN",
    "T1": "DVKHTC1",
}

# Transaction type rules
IMMEDIATE_DAYS = 2  # GN (giao ngay) - up to 2 business days
FORWARD_DAYS = 3    # KH (kỳ hạn) - 3+ business days

# API Configuration
API_TITLE = "MBNT System API"
API_DESCRIPTION = "Internal Foreign Currency Trading System for VCB"
API_VERSION = "1.0.0"
