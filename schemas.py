from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import Optional, List
from models import UserRole, TransactionDirection, TransactionType, MessageType, TransactionStatus

# ============== Auth Schemas ==============
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    username: str
    full_name: str
    role: str
    department: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str
    
    @field_validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain digit')
        if not any(c in '@$!%*?&' for c in v):
            raise ValueError('Password must contain special character')
        return v

class ResetPasswordRequest(BaseModel):
    user_id: int
    new_password: str = "Vcb@1234"

# ============== User Schemas ==============
class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    role: str = UserRole.PNV.value
    department: str
    is_active: bool = True

class UserCreate(UserBase):
    password: str = "Vcb@1234"
    bgd_manager_id: Optional[int] = None  # For BGD management

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[str] = None
    bgd_manager_id: Optional[int] = None

class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime]
    
    class Config:
        from_attributes = True

class UserListResponse(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    department: str
    is_active: bool
    last_login: Optional[datetime]
    
    class Config:
        from_attributes = True

# ============== Customer Schemas ==============
class CustomerBase(BaseModel):
    cif: str = Field(..., max_length=10)
    customer_name: str

class CustomerCreate(CustomerBase):
    pnv_user_id: Optional[int] = None

class CustomerUpdate(BaseModel):
    customer_name: Optional[str] = None
    pnv_user_id: Optional[int] = None

class CustomerResponse(CustomerBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# ============== Purpose/Source Schemas ==============
class PurposeSourceBase(BaseModel):
    code: int = Field(..., ge=1, le=12)
    name: str
    type: str  # "purpose" or "source"
    currency: Optional[str] = None

class PurposeSourceCreate(PurposeSourceBase):
    pass

class PurposeSourceResponse(PurposeSourceBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

# ============== Transaction Schemas ==============
class QuotationDetail(BaseModel):
    buy_rate: float
    sell_rate: float
    validity_minutes: int = 5

class TransactionRequestBase(BaseModel):
    cif: str = Field(..., max_length=10)
    direction: str  # buy or sell
    transaction_date: datetime
    effective_date: datetime
    currency_code: str = Field(..., max_length=3)
    buy_currency: str = Field(..., max_length=3)
    sell_currency: str = Field(..., max_length=3)
    amount: float = Field(..., gt=0)
    purpose_source_code: int = Field(..., ge=1, le=12)

class TransactionRequest(TransactionRequestBase):
    """Request from PNV to ask for quotation"""
    pass

class QuotationRequest(BaseModel):
    """Quotation from PQL to PNV"""
    transaction_id: int
    buy_rate: float
    sell_rate: float
    validity_minutes: int = 5

class TransactionAccept(BaseModel):
    """PNV accepts quotation"""
    transaction_id: int
    quotation_id: int

class TransactionReject(BaseModel):
    """PNV rejects quotation"""
    transaction_id: int
    quotation_id: int
    reason: Optional[str] = None

class TransactionInterrupt(BaseModel):
    """PQL interrupts quotation"""
    transaction_id: int
    quotation_id: int
    interrupt_all: bool = False

class TransactionUpdate(BaseModel):
    """Update completed transaction"""
    buy_rate: Optional[float] = None
    sell_rate: Optional[float] = None
    transaction_type: Optional[str] = None
    amount: Optional[float] = None
    profit: Optional[float] = None

class TransactionResponse(BaseModel):
    id: int
    transaction_no: str
    direction: str
    customer_id: int
    currency_code: str
    buy_currency: str
    sell_currency: str
    amount: float
    corresponding_amount: Optional[float]
    transaction_date: datetime
    effective_date: datetime
    buy_rate: Optional[float]
    sell_rate: Optional[float]
    transaction_type: str
    purpose_source_code: int
    status: str
    profit: Optional[float]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class BlotterResponse(BaseModel):
    """Blotter entry"""
    id: int
    transaction_no: str
    cif: str
    customer_name: str
    direction: str
    currency_code: str
    amount: float
    buy_currency: str
    sell_currency: str
    buy_rate: Optional[float]
    sell_rate: Optional[float]
    transaction_date: datetime
    effective_date: datetime
    transaction_type: str
    purpose_source_code: int
    corresponding_amount: Optional[float]
    profit: Optional[float]
    status: str
    updated_at: datetime

class ExchangeRateBalanceRequest(BaseModel):
    """Exchange rate balance for report"""
    transaction_id: int
    balance_rate: float

# ============== Message Schemas ==============
class MessageBase(BaseModel):
    content: str
    message_type: str = MessageType.CHAT.value  # quotation or chat
    recipient_department: Optional[str] = None  # For PQL sending to PNV
    recipient_ids: Optional[str] = None  # CSV of user IDs

class MessageCreate(MessageBase):
    transaction_id: Optional[int] = None

class MessageResponse(BaseModel):
    id: int
    sender_id: int
    sender_username: str
    message_type: str
    content: str
    created_at: datetime
    is_read: bool
    transaction_id: Optional[int] = None
    
    class Config:
        from_attributes = True

# ============== Report Schemas ==============
class ReportFilter(BaseModel):
    transaction_date_from: Optional[datetime] = None
    transaction_date_to: Optional[datetime] = None
    effective_date_from: Optional[datetime] = None
    effective_date_to: Optional[datetime] = None
    buy_currency: Optional[str] = None
    sell_currency: Optional[str] = None
    pnv_department: Optional[str] = None
    transaction_type: Optional[str] = None

class ReportSummary(BaseModel):
    total_transactions: int
    total_volume: float
    total_profit: float
    transactions: List[BlotterResponse]

# ============== File Upload Schemas ==============
class FileUploadResponse(BaseModel):
    id: int
    file_name: str
    file_type: str
    sheets_processed: int
    records_imported: int
    status: str
    uploaded_at: datetime
    errors: Optional[str] = None
    
    class Config:
        from_attributes = True

# ============== Dashboard Schemas ==============
class DashboardStats(BaseModel):
    total_transactions: int
    pending_quotations: int
    completed_today: int
    total_volume: float
    total_profit: float
    unread_messages: int

class NotificationMessage(BaseModel):
    id: int
    type: str  # quotation or chat
    message: str
    sender: str
    created_at: datetime
    is_read: bool
    transaction_id: Optional[int] = None
