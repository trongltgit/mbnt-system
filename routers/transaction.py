from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from database import get_db
from models import User, Transaction, Customer, QuotationHistory, Message, TransactionEdit, TransactionStatus, UserRole, MessageType, TransactionType, ExchangeRateBalance
from schemas import TransactionRequest, TransactionResponse, QuotationRequest, TransactionAccept, TransactionReject, TransactionInterrupt, TransactionUpdate, BlotterResponse, ExchangeRateBalanceRequest
from auth import get_current_user
from config import IMMEDIATE_DAYS, FORWARD_DAYS
import uuid

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

def check_pnv(current_user: User = Depends(get_current_user)):
    """Check if current user is PNV"""
    if current_user.role != UserRole.PNV.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only PNV can access this endpoint"
        )
    return current_user

def check_pql(current_user: User = Depends(get_current_user)):
    """Check if current user is PQL"""
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only PQL can access this endpoint"
        )
    return current_user

@router.post("/request", response_model=TransactionResponse)
def request_quotation(
    request: TransactionRequest,
    pnv_user: User = Depends(check_pnv),
    db: Session = Depends(get_db)
):
    """PNV requests quotation from PQL"""
    # Get or create customer
    customer = db.query(Customer).filter(Customer.cif == request.cif).first()
    if not customer:
        customer = Customer(
            cif=request.cif,
            customer_name=request.cif,  # Should be loaded from uploaded data
            pnv_user_id=pnv_user.id
        )
        db.add(customer)
        db.flush()
    
    # Validate currencies
    if request.buy_currency == request.sell_currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Buy and sell currencies cannot be the same"
        )
    
    # Create transaction
    transaction_no = f"TXN-{pnv_user.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}"
    
    new_transaction = Transaction(
        transaction_no=transaction_no,
        pnv_id=pnv_user.id,
        customer_id=customer.id,
        direction=request.direction,
        transaction_date=request.transaction_date,
        effective_date=request.effective_date,
        currency_code=request.currency_code,
        buy_currency=request.buy_currency,
        sell_currency=request.sell_currency,
        amount=request.amount,
        purpose_source_code=request.purpose_source_code,
        status=TransactionStatus.PENDING.value
    )
    
    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)
    
    # Create notification message to PQL
    message = Message(
        sender_id=pnv_user.id,
        recipient_department="PQL",
        transaction_id=new_transaction.id,
        message_type=MessageType.QUOTATION.value,
        content=f"Request quotation for {request.amount} {request.currency_code}"
    )
    db.add(message)
    db.commit()
    
    return new_transaction

@router.post("/quotation", response_model=TransactionResponse)
def submit_quotation(
    request: QuotationRequest,
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """PQL submits quotation to PNV"""
    # Get transaction
    transaction = db.query(Transaction).filter(
        Transaction.id == request.transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    if transaction.status not in [TransactionStatus.PENDING.value, TransactionStatus.QUOTED.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction cannot receive quotation in current status"
        )
    
    # Create quotation history
    expires_at = datetime.utcnow() + timedelta(minutes=request.validity_minutes)
    
    quotation = QuotationHistory(
        transaction_id=transaction.id,
        quoted_by=pql_user.id,
        buy_rate=request.buy_rate,
        sell_rate=request.sell_rate,
        validity_minutes=request.validity_minutes,
        expires_at=expires_at,
        status="active"
    )
    
    db.add(quotation)
    
    # Update transaction
    transaction.buy_rate = request.buy_rate
    transaction.sell_rate = request.sell_rate
    transaction.quoted_at = datetime.utcnow()
    transaction.quote_validity_minutes = request.validity_minutes
    transaction.status = TransactionStatus.QUOTED.value
    
    db.commit()
    
    # Create notification message
    message = Message(
        sender_id=pql_user.id,
        transaction_id=transaction.id,
        message_type=MessageType.QUOTATION.value,
        content=f"Quotation: Buy {request.buy_rate}, Sell {request.sell_rate}"
    )
    db.add(message)
    db.commit()
    
    db.refresh(transaction)
    return transaction

@router.post("/accept", response_model=TransactionResponse)
def accept_quotation(
    request: TransactionAccept,
    pnv_user: User = Depends(check_pnv),
    db: Session = Depends(get_db)
):
    """PNV accepts quotation"""
    # Get transaction and quotation
    transaction = db.query(Transaction).filter(
        Transaction.id == request.transaction_id,
        Transaction.pnv_id == pnv_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    quotation = db.query(QuotationHistory).filter(
        QuotationHistory.id == request.quotation_id,
        QuotationHistory.transaction_id == request.transaction_id
    ).first()
    
    if not quotation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quotation not found"
        )
    
    # Check if quotation has expired
    if datetime.utcnow() > quotation.expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quotation has expired"
        )
    
    # Update transaction status
    transaction.status = TransactionStatus.ACCEPTED.value
    quotation.status = "accepted"
    
    # Calculate corresponding amount
    if transaction.direction == "buy":
        transaction.corresponding_amount = transaction.amount / quotation.buy_rate
    else:
        transaction.corresponding_amount = transaction.amount * quotation.sell_rate
    
    # Calculate profit
    if transaction.direction == "buy":
        transaction.profit = transaction.corresponding_amount * (quotation.buy_rate - quotation.sell_rate)
    else:
        transaction.profit = transaction.corresponding_amount * (quotation.sell_rate - quotation.buy_rate)
    
    # Determine transaction type based on effective date
    business_days = calculate_business_days(transaction.transaction_date, transaction.effective_date)
    if business_days <= IMMEDIATE_DAYS:
        transaction.transaction_type = TransactionType.GN.value
    else:
        transaction.transaction_type = TransactionType.KH.value
    
    db.commit()
    db.refresh(transaction)
    return transaction

@router.post("/reject")
def reject_quotation(
    request: TransactionReject,
    pnv_user: User = Depends(check_pnv),
    db: Session = Depends(get_db)
):
    """PNV rejects quotation"""
    transaction = db.query(Transaction).filter(
        Transaction.id == request.transaction_id,
        Transaction.pnv_id == pnv_user.id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    quotation = db.query(QuotationHistory).filter(
        QuotationHistory.id == request.quotation_id
    ).first()
    
    if quotation:
        quotation.status = "rejected"
    
    # Keep transaction in pending status so PNV can request again
    transaction.status = TransactionStatus.PENDING.value
    
    db.commit()
    
    return {"message": "Quotation rejected", "transaction_id": request.transaction_id}

@router.post("/interrupt")
def interrupt_quotation(
    request: TransactionInterrupt,
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """PQL interrupts quotation(s)"""
    quotation = db.query(QuotationHistory).filter(
        QuotationHistory.id == request.quotation_id
    ).first()
    
    if not quotation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quotation not found"
        )
    
    if request.interrupt_all:
        # Interrupt all active quotations for all transactions by this PQL
        active_quotations = db.query(QuotationHistory).filter(
            QuotationHistory.quoted_by == pql_user.id,
            QuotationHistory.status == "active"
        ).all()
        
        for q in active_quotations:
            q.status = "interrupted"
            q.transaction.status = TransactionStatus.INTERRUPTED.value
    else:
        # Interrupt only this quotation
        quotation.status = "interrupted"
        quotation.transaction.status = TransactionStatus.INTERRUPTED.value
    
    db.commit()
    return {"message": "Quotation interrupted"}

@router.put("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: int,
    request: TransactionUpdate,
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """PQL updates completed transaction"""
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    if transaction.status != TransactionStatus.ACCEPTED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only edit accepted transactions"
        )
    
    # Track edits
    if request.buy_rate and request.buy_rate != transaction.buy_rate:
        edit = TransactionEdit(
            transaction_id=transaction.id,
            edited_by=pql_user.id,
            field_name="buy_rate",
            old_value=str(transaction.buy_rate),
            new_value=str(request.buy_rate)
        )
        db.add(edit)
        transaction.buy_rate = request.buy_rate
    
    if request.sell_rate and request.sell_rate != transaction.sell_rate:
        edit = TransactionEdit(
            transaction_id=transaction.id,
            edited_by=pql_user.id,
            field_name="sell_rate",
            old_value=str(transaction.sell_rate),
            new_value=str(request.sell_rate)
        )
        db.add(edit)
        transaction.sell_rate = request.sell_rate
    
    if request.transaction_type:
        edit = TransactionEdit(
            transaction_id=transaction.id,
            edited_by=pql_user.id,
            field_name="transaction_type",
            old_value=transaction.transaction_type,
            new_value=request.transaction_type
        )
        db.add(edit)
        transaction.transaction_type = request.transaction_type
    
    if request.amount:
        edit = TransactionEdit(
            transaction_id=transaction.id,
            edited_by=pql_user.id,
            field_name="amount",
            old_value=str(transaction.amount),
            new_value=str(request.amount)
        )
        db.add(edit)
        transaction.amount = request.amount
    
    if request.profit is not None:
        edit = TransactionEdit(
            transaction_id=transaction.id,
            edited_by=pql_user.id,
            field_name="profit",
            old_value=str(transaction.profit),
            new_value=str(request.profit)
        )
        db.add(edit)
        transaction.profit = request.profit
    
    transaction.last_edited_by = pql_user.id
    transaction.last_edited_at = datetime.utcnow()
    
    db.commit()
    db.refresh(transaction)
    return transaction

@router.get("/blotter")
def get_blotter(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = Query(0),
    limit: int = Query(100),
    transaction_type: str = None,
    currency_code: str = None,
    start_date: datetime = None,
    end_date: datetime = None
):
    """Get blotter based on user role"""
    query = db.query(
        Transaction.id,
        Transaction.transaction_no,
        Customer.cif,
        Customer.customer_name,
        Transaction.direction,
        Transaction.currency_code,
        Transaction.amount,
        Transaction.buy_currency,
        Transaction.sell_currency,
        Transaction.buy_rate,
        Transaction.sell_rate,
        Transaction.transaction_date,
        Transaction.effective_date,
        Transaction.transaction_type,
        Transaction.purpose_source_code,
        Transaction.corresponding_amount,
        Transaction.profit,
        Transaction.status,
        Transaction.updated_at
    ).join(Customer, Transaction.customer_id == Customer.id).filter(
        Transaction.status == TransactionStatus.ACCEPTED.value
    )
    
    # Apply role-based filtering
    if current_user.role == UserRole.PNV.value:
        # PNV sees only their own transactions
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PQL.value:
        # PQL sees all transactions (but only accepted ones)
        pass
    elif current_user.role == UserRole.BGD.value:
        # BGD sees transactions from PNV they manage
        managed_pnv_ids = db.query(BGDManagement).filter(
            BGDManagement.bgd_id == current_user.id
        ).all()
        pnv_ids = [m.pnv_user_id for m in managed_pnv_ids]
        query = query.filter(Transaction.pnv_id.in_(pnv_ids))
    
    # Apply filters
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)
    if currency_code:
        query = query.filter(Transaction.currency_code == currency_code)
    if start_date:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(Transaction.transaction_date <= end_date)
    
    # Count before pagination
    total = query.count()
    
    # Apply pagination
    transactions = query.offset(skip).limit(limit).all()
    
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "transactions": transactions
    }

@router.post("/exchange-rate-balance")
def add_exchange_rate_balance(
    request: ExchangeRateBalanceRequest,
    pql_user: User = Depends(check_pql),
    db: Session = Depends(get_db)
):
    """PQL adds exchange rate balance (tỷ giá cân đối) for report"""
    transaction = db.query(Transaction).filter(
        Transaction.id == request.transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    # Check if already exists
    existing = db.query(ExchangeRateBalance).filter(
        ExchangeRateBalance.transaction_id == request.transaction_id
    ).first()
    
    if existing:
        existing.balance_rate = request.balance_rate
        existing.updated_at = datetime.utcnow()
    else:
        balance = ExchangeRateBalance(
            transaction_id=request.transaction_id,
            balance_rate=request.balance_rate,
            created_by=pql_user.id
        )
        db.add(balance)
    
    db.commit()
    return {"message": "Exchange rate balance updated"}

def calculate_business_days(start_date: datetime, end_date: datetime) -> int:
    """Calculate business days between two dates"""
    business_days = 0
    current = start_date
    while current < end_date:
        # Skip weekends (5=Saturday, 6=Sunday)
        if current.weekday() < 5:
            business_days += 1
        current += timedelta(days=1)
    return business_days
