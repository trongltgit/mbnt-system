from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Text, Enum, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from database import Base

# Enums
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    PNV = "pnv"  # Phòng Nghiệp Vụ
    PQL = "pql"  # Phòng Quản Lý
    BGD = "bgd"  # Ban Giám Đốc

class TransactionType(str, enum.Enum):
    GN = "GN"   # Giao Ngay (Immediate)
    KH = "KH"   # Kỳ Hạn (Forward)
    HD = "HĐ"   # Hoán Đổi (Swap)

class TransactionDirection(str, enum.Enum):
    BUY = "buy"   # VCB mua
    SELL = "sell" # VCB bán

class MessageType(str, enum.Enum):
    QUOTATION = "quotation"  # Chào giá (red notification)
    CHAT = "chat"            # Chat (green notification)

class TransactionStatus(str, enum.Enum):
    PENDING = "pending"           # Đang chờ
    QUOTED = "quoted"             # Đã chào giá
    ACCEPTED = "accepted"         # Đã chấp nhận
    REJECTED = "rejected"         # Bị từ chối
    INTERRUPTED = "interrupted"  # Bị giành lại
    EXPIRED = "expired"           # Hết hiệu lực

# Users Table
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(100), unique=True, index=True)
    hashed_password = Column(String(255))
    full_name = Column(String(100))
    role = Column(String(20), default=UserRole.PNV.value)
    department = Column(String(50))  # Phòng ban
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # Relationships
    transactions_sent = relationship("Transaction", foreign_keys="Transaction.pnv_id", back_populates="pnv")
    messages_sent = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    quotations_sent = relationship("QuotationHistory", back_populates="quoted_by")
    edits = relationship("TransactionEdit", back_populates="edited_by")
    managed_pnv_users = relationship("BGDManagement", foreign_keys="BGDManagement.bgd_id", back_populates="bgd_user")
    
    def __repr__(self):
        return f"<User {self.username} - {self.role} - {self.department}>"

# BGD Management - Track which PNV users are managed by which BGD user
class BGDManagement(Base):
    __tablename__ = "bgd_management"
    
    id = Column(Integer, primary_key=True, index=True)
    bgd_id = Column(Integer, ForeignKey("users.id"))
    pnv_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    bgd_user = relationship("User", foreign_keys=[bgd_id], back_populates="managed_pnv_users")

# Customers Table (CIF - Tên KH)
class Customer(Base):
    __tablename__ = "customers"
    
    id = Column(Integer, primary_key=True, index=True)
    cif = Column(String(10), unique=True, index=True)
    customer_name = Column(String(255), index=True)
    pnv_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    transactions = relationship("Transaction", back_populates="customer")
    
    def __repr__(self):
        return f"<Customer {self.cif} - {self.customer_name}>"

# Purposes/Sources Table
class PurposeSource(Base):
    __tablename__ = "purposes_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(Integer, index=True)  # 1-12
    name = Column(String(255))
    type = Column(String(20))  # "purpose" hoặc "source"
    currency = Column(String(3), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<PurposeSource {self.code} - {self.name} ({self.type})>"

# Transactions Table (giao dịch MBNT)
class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_no = Column(String(50), unique=True, index=True)
    pnv_id = Column(Integer, ForeignKey("users.id"))
    customer_id = Column(Integer, ForeignKey("customers.id"))
    
    # Transaction details
    direction = Column(String(10))  # buy/sell
    transaction_date = Column(DateTime, index=True)
    effective_date = Column(DateTime, index=True)
    
    # Currency and amounts
    currency_code = Column(String(3), index=True)  # Mã tiền tệ giao dịch
    buy_currency = Column(String(3))  # Đồng tiền mua
    sell_currency = Column(String(3))  # Đồng tiền bán
    amount = Column(Float)  # Số lượng ngoại tệ giao dịch
    corresponding_amount = Column(Float, nullable=True)  # Số lượng tương ứng
    
    # Quotation details
    buy_rate = Column(Float, nullable=True)  # Tỷ giá mua
    sell_rate = Column(Float, nullable=True)  # Tỷ giá bán
    quoted_rate = Column(Float, nullable=True)  # Tỷ giá chào
    quoted_at = Column(DateTime, nullable=True)  # Thời gian chào giá
    quote_validity_minutes = Column(Integer, default=5)  # Phút hiệu lực
    
    # Transaction type
    transaction_type = Column(String(3))  # GN/KH/HĐ
    purpose_source_code = Column(Integer, nullable=True)  # Mục đích/Nguồn
    
    # Status and profit
    status = Column(String(20), default=TransactionStatus.PENDING.value, index=True)
    profit = Column(Float, nullable=True)  # Lợi nhuận
    
    # Editing tracking
    last_edited_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_edited_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    pnv = relationship("User", foreign_keys=[pnv_id], back_populates="transactions_sent")
    customer = relationship("Customer", back_populates="transactions")
    quotations = relationship("QuotationHistory", back_populates="transaction")
    edits = relationship("TransactionEdit", back_populates="transaction")
    messages = relationship("Message", back_populates="transaction")
    
    def __repr__(self):
        return f"<Transaction {self.transaction_no} - {self.direction} {self.amount}{self.currency_code}>"

# Quotation History Table
class QuotationHistory(Base):
    __tablename__ = "quotation_history"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))
    quoted_by = Column(Integer, ForeignKey("users.id"))
    buy_rate = Column(Float)
    sell_rate = Column(Float)
    validity_minutes = Column(Integer)
    status = Column(String(20), default="active")  # active, withdrawn, interrupted, expired
    quoted_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    
    # Relationships
    transaction = relationship("Transaction", back_populates="quotations")
    quoted_user = relationship("User", foreign_keys=[quoted_by], back_populates="quotations_sent")
    
    def __repr__(self):
        return f"<QuotationHistory {self.transaction_id} - {self.buy_rate}/{self.sell_rate}>"

# Transaction Edit Log
class TransactionEdit(Base):
    __tablename__ = "transaction_edits"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))
    edited_by = Column(Integer, ForeignKey("users.id"))
    field_name = Column(String(50))
    old_value = Column(String(255), nullable=True)
    new_value = Column(String(255), nullable=True)
    edited_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    transaction = relationship("Transaction", back_populates="edits")
    edited_user = relationship("User", foreign_keys=[edited_by], back_populates="edits")

# Messages/Chat Table
class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    recipient_department = Column(String(50), nullable=True)  # Phòng nhận
    recipient_ids = Column(String(255), nullable=True)  # CSV của user IDs nhận
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    
    message_type = Column(String(20), default=MessageType.CHAT.value)  # quotation/chat
    content = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    sender = relationship("User", foreign_keys=[sender_id], back_populates="messages_sent")
    transaction = relationship("Transaction", back_populates="messages")
    
    def __repr__(self):
        return f"<Message from {self.sender_id} - {self.message_type}>"

# Exchange Rate Balance Table (Tỷ giá cân đối)
class ExchangeRateBalance(Base):
    __tablename__ = "exchange_rate_balance"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))
    balance_rate = Column(Float)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ExchangeRateBalance {self.balance_rate}>"

# File Upload Log
class FileUpload(Base):
    __tablename__ = "file_uploads"
    
    id = Column(Integer, primary_key=True, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    file_name = Column(String(255))
    file_path = Column(String(500))
    file_type = Column(String(50))  # cif-name, purpose-source, chân hàng, etc.
    sheets_processed = Column(Integer, default=0)
    records_imported = Column(Integer, default=0)
    errors = Column(Text, nullable=True)
    status = Column(String(20), default="success")  # success/error/partial
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<FileUpload {self.file_name} - {self.file_type}>"

# Audit Log
class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(255))
    resource_type = Column(String(50))
    resource_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f"<AuditLog {self.action} on {self.resource_type}>"
