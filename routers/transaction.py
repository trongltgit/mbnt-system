"""
💱 Transaction Router - Quản lý giao dịch ngoại hối
- Chào giá (quote)
- Interrupt chào giá (dừng nhưng không đóng modal)
- Resubmit chào giá mới
- Reject và xử lý modal
- Phân quyền: PNV thấy của mình, PQL thấy tất cả, không thấy system_rate
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging

from database import SessionLocal
from models import (
    Transaction, TransactionStatus, User, UserRole, Message, MessageType,
    QuotationHistory, TransactionEdit, AuditLog
)
from permissions import PermissionManager, check_role
from realtime_handler import RealtimeEventEmitter, pause_timer, register_timer
from excel_export import ExcelExporter, CSVExporter, PDFExporter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/transactions",
    tags=["transactions"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = None) -> User:
    """Get current user from token (simplified)"""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    db = SessionLocal()
    user = db.query(User).filter(User.username == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user


@router.get("/health")
async def health_check():
    """🏥 Health check"""
    return {"status": "healthy", "service": "transactions"}


@router.get("/", response_model=List[dict])
async def list_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📋 Liệt kê giao dịch
    
    🆕 PNV không thấy system_rate
    PQL/BGD/PGD: thấy hết
    """
    
    query = db.query(Transaction)
    
    # Filter by role
    if current_user.role == UserRole.PNV.value:
        # PNV: chỉ thấy của mình
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        # PGD: thấy của phòng mình
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    # PQL/BGD: thấy tất cả
    
    transactions = query.order_by(Transaction.created_at.desc()).all()
    
    # Filter sensitive data
    result = []
    for txn in transactions:
        txn_dict = {
            "id": txn.id,
            "transaction_no": txn.transaction_no,
            "transaction_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
            "customer": txn.customer.customer_name if txn.customer else "",
            "direction": txn.direction,
            "currency": txn.currency_code,
            "amount": txn.amount,
            "buy_rate": txn.buy_rate,
            "sell_rate": txn.sell_rate,
            "profit": txn.profit,
            "status": txn.status,
            "pnv": txn.pnv.full_name if txn.pnv else "",
            "created_at": txn.created_at.isoformat() if txn.created_at else None
        }
        
        # Chỉ PQL/BGD/PGD thấy system_rate
        if PermissionManager.can_see_system_rate(current_user.role):
            txn_dict["system_buy_rate"] = txn.system_buy_rate
            txn_dict["system_sell_rate"] = txn.system_sell_rate
        
        # Filter via permission manager
        txn_dict = PermissionManager.filter_sensitive_fields(txn_dict, current_user.role)
        
        result.append(txn_dict)
    
    return result


@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📄 Lấy chi tiết giao dịch"""
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check permission
    if not PermissionManager.can_view_transaction(
        current_user.role, txn.pnv_id, current_user.id,
        current_user.department, txn.pnv.department if txn.pnv else None
    ):
        raise HTTPException(status_code=403, detail="Không có quyền xem giao dịch này")
    
    result = {
        "id": txn.id,
        "transaction_no": txn.transaction_no,
        "transaction_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
        "customer": txn.customer.customer_name if txn.customer else "",
        "direction": txn.direction,
        "currency": txn.currency_code,
        "amount": txn.amount,
        "buy_rate": txn.buy_rate,
        "sell_rate": txn.sell_rate,
        "profit": txn.profit,
        "status": txn.status,
        "pnv": txn.pnv.full_name if txn.pnv else "",
        "created_at": txn.created_at.isoformat() if txn.created_at else None
    }
    
    # Show system rates if user has permission
    if PermissionManager.can_see_system_rate(current_user.role):
        result["system_buy_rate"] = txn.system_buy_rate
        result["system_sell_rate"] = txn.system_sell_rate
    
    return PermissionManager.filter_sensitive_fields(result, current_user.role)


# 🆕 INTERRUPT ENDPOINT
@router.put("/{transaction_id}/interrupt")
async def interrupt_quote(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ⏹️ Giành lại chào giá (PQL only)
    
    🆕 Modal KHÔNG đóng, chỉ dừng countdown
    Chuyển sang tab RESUBMIT để nhập giá mới
    """
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Chỉ PQL mới giành lại
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(status_code=403, detail="Only PQL can interrupt")
    
    # Dừng countdown nhưng không xóa
    quote = db.query(QuotationHistory).filter(
        QuotationHistory.transaction_id == transaction_id,
        QuotationHistory.status == "active"
    ).first()
    
    if quote:
        quote.status = "interrupted"
        pause_timer(quote.id)  # ⏸️ Dừng, không xóa
        
        # Ghi log
        audit = AuditLog(
            user_id=current_user.id,
            action="interrupt_quote",
            resource_type="quotation",
            resource_id=quote.id,
            details=f"Interrupted quote {quote.id} for transaction {transaction_id}"
        )
        db.add(audit)
        
        # Emit event
        await RealtimeEventEmitter.quote_interrupted(
            quote_id=quote.id,
            transaction_id=transaction_id,
            interrupted_by=current_user.id,
            interrupted_by_name=current_user.full_name
        )
        
        db.commit()
        logger.info(f"✅ Quote interrupted by PQL: {current_user.username}")
    
    return {
        "success": True,
        "transaction_id": transaction_id,
        "status": "interrupted",
        "modal_action": "keep_open",  # ⚠️ MODAL KHÔNG ĐÓNG
        "tab_switch": "resubmit",  # 🔄 Chuyển sang RESUBMIT tab
        "quote_id": quote.id if quote else None,
        "message": "Quote interrupted. Switch to RESUBMIT to enter new price."
    }


# 🆕 RESUBMIT ENDPOINT
@router.put("/{transaction_id}/resubmit")
async def resubmit_quote(
    transaction_id: int,
    buy_rate: float,
    sell_rate: float,
    reason: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📝 Resubmit chào giá mới
    PQL nhập giá mới sau khi interrupt hoặc reject
    """
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Chỉ PQL mới resubmit
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(status_code=403, detail="Only PQL can resubmit")
    
    # Validate rates
    if buy_rate <= 0 or sell_rate <= 0:
        raise HTTPException(status_code=400, detail="Invalid rates")
    
    # Lưu giá cũ
    old_buy = txn.buy_rate
    old_sell = txn.sell_rate
    
    # Update giá mới
    txn.buy_rate = buy_rate
    txn.sell_rate = sell_rate
    txn.system_buy_rate = buy_rate  # System rate = quoted rate
    txn.system_sell_rate = sell_rate
    txn.status = TransactionStatus.PENDING.value
    
    # Ghi log chỉnh sửa
    edit_log = TransactionEdit(
        transaction_id=transaction_id,
        edited_by=current_user.id,
        edited_by_name=current_user.full_name,
        field_name="buy_rate,sell_rate",
        old_value=f"{old_buy}/{old_sell}",
        new_value=f"{buy_rate}/{sell_rate}",
        reason=reason or "Resubmit after interrupt/reject",
        change_type="quote_resubmit",
        edited_at=datetime.utcnow()
    )
    db.add(edit_log)
    
    # Ghi audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="resubmit_quote",
        resource_type="transaction",
        resource_id=transaction_id,
        details=f"Resubmitted quote: {old_buy}/{old_sell} -> {buy_rate}/{sell_rate}"
    )
    db.add(audit)
    
    db.commit()
    
    logger.info(f"✅ Quote resubmitted by PQL: {current_user.username}")
    
    # Emit update
    await RealtimeEventEmitter.transaction_updated(
        transaction_id=transaction_id,
        transaction_data={
            "buy_rate": buy_rate,
            "sell_rate": sell_rate,
            "status": txn.status
        },
        user_id=txn.pnv_id
    )
    
    return {
        "success": True,
        "transaction_id": transaction_id,
        "buy_rate": buy_rate,
        "sell_rate": sell_rate,
        "old_buy_rate": old_buy,
        "old_sell_rate": old_sell,
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Quote resubmitted successfully. Awaiting PNV response."
    }


# 🆕 MODIFIED REJECT ENDPOINT
@router.put("/{transaction_id}/reject")
async def reject_quote(
    transaction_id: int,
    reason: str = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ❌ Từ chối chào giá (PNV only)
    
    🆕 Modal KHÔNG đóng (chỉ đóng khi PNV click close)
    PQL vẫn có thể resubmit chào giá mới
    """
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Chỉ PNV mới reject
    if current_user.role != UserRole.PNV.value:
        raise HTTPException(status_code=403, detail="Only PNV can reject")
    
    # Check permission to reject this transaction
    if txn.pnv_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only reject your own transactions")
    
    quote = db.query(QuotationHistory).filter(
        QuotationHistory.transaction_id == transaction_id,
        QuotationHistory.status == "active"
    ).first()
    
    if quote:
        quote.status = "rejected"
        pause_timer(quote.id)  # ⏸️ Dừng countdown
        
        txn.status = TransactionStatus.REJECTED.value
        
        # Lấy thông tin người quote
        quote_author = db.query(User).filter(User.id == quote.quoted_by).first()
        
        # Tạo message cho PQL
        msg = Message(
            sender_id=current_user.id,
            sender_name=current_user.full_name,
            sender_role=current_user.role,
            sender_department=current_user.department,
            recipient_id=quote.quoted_by,
            recipient_name=quote_author.full_name if quote_author else "Unknown",
            recipient_role="pql",
            message_type=MessageType.CHAT.value,
            content=f"Quote rejected. Reason: {reason or 'Not specified'}",
            transaction_id=transaction_id,
            question_content=f"Transaction {txn.transaction_no}",
            answer_content=None,  # Chờ PQL resubmit
            status="pending_response"
        )
        db.add(msg)
        
        # Ghi audit log
        audit = AuditLog(
            user_id=current_user.id,
            action="reject_quote",
            resource_type="quotation",
            resource_id=quote.id,
            details=f"Rejected quote: {reason}"
        )
        db.add(audit)
        
        db.commit()
        logger.info(f"✅ Quote rejected by PNV: {current_user.username}")
    
    return {
        "success": True,
        "transaction_id": transaction_id,
        "status": "rejected",
        "modal_action": "keep_open",  # ⚠️ MODAL KHÔNG ĐÓNG
        "can_pql_resubmit": True,  # PQL có thể resubmit
        "message": "Quote rejected. PQL can resubmit new quote."
    }


@router.put("/{transaction_id}/accept")
async def accept_quote(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """✅ Chấp nhận chào giá (PNV only)"""
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Chỉ PNV mới accept
    if current_user.role != UserRole.PNV.value:
        raise HTTPException(status_code=403, detail="Only PNV can accept")
    
    # Check permission
    if txn.pnv_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only accept your own transactions")
    
    quote = db.query(QuotationHistory).filter(
        QuotationHistory.transaction_id == transaction_id,
        QuotationHistory.status == "active"
    ).first()
    
    if quote:
        quote.status = "accepted"
        pause_timer(quote.id)
        
        txn.status = TransactionStatus.ACCEPTED.value
        txn.accepted_at = datetime.utcnow()
        
        # Ghi audit log
        audit = AuditLog(
            user_id=current_user.id,
            action="accept_quote",
            resource_type="quotation",
            resource_id=quote.id,
            details=f"Accepted quote for transaction {transaction_id}"
        )
        db.add(audit)
        
        db.commit()
        logger.info(f"✅ Quote accepted by PNV: {current_user.username}")
        
        # Emit real-time update for blotter
        await RealtimeEventEmitter.transaction_updated(
            transaction_id=transaction_id,
            transaction_data={
                "status": "accepted",
                "accepted_at": txn.accepted_at.isoformat()
            },
            user_id=txn.pnv_id
        )
    
    return {
        "success": True,
        "transaction_id": transaction_id,
        "status": "accepted",
        "accepted_at": txn.accepted_at.isoformat() if txn.accepted_at else None,
        "message": "Quote accepted successfully. Blotter updated in real-time."
    }


@router.post("/{transaction_id}/quote")
async def send_quote(
    transaction_id: int,
    buy_rate: float,
    sell_rate: float,
    countdown: int = 60,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """💬 Gửi chào giá mới (PQL only)"""
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Chỉ PQL mới gửi chào giá
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(status_code=403, detail="Only PQL can send quotes")
    
    # Validate
    if buy_rate <= 0 or sell_rate <= 0:
        raise HTTPException(status_code=400, detail="Invalid rates")
    
    # Tạo quotation history
    quote = QuotationHistory(
        transaction_id=transaction_id,
        quoted_by=current_user.id,
        quoted_by_name=current_user.full_name,
        buy_rate=buy_rate,
        sell_rate=sell_rate,
        status="active",
        countdown_seconds=countdown,
        quoted_at=datetime.utcnow()
    )
    db.add(quote)
    db.commit()
    
    # Start countdown timer
    register_timer(quote.id, countdown)
    
    # Ghi audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="send_quote",
        resource_type="quotation",
        resource_id=quote.id,
        details=f"Sent quote: {buy_rate}/{sell_rate} with countdown {countdown}s"
    )
    db.add(audit)
    db.commit()
    
    logger.info(f"✅ Quote sent by PQL: {current_user.username}")
    
    # Emit real-time event
    await RealtimeEventEmitter.quote_sent(
        quote_id=quote.id,
        transaction_id=transaction_id,
        buy_rate=buy_rate,
        sell_rate=sell_rate,
        countdown=countdown,
        user_id=txn.pnv_id
    )
    
    return {
        "success": True,
        "quote_id": quote.id,
        "transaction_id": transaction_id,
        "buy_rate": buy_rate,
        "sell_rate": sell_rate,
        "countdown": countdown,
        "quoted_at": quote.quoted_at.isoformat(),
        "message": "Quote sent. Countdown timer started."
    }


@router.get("/{transaction_id}/history")
async def get_quote_history(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📜 Lịch sử chào giá"""
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check permission
    if not PermissionManager.can_view_transaction(
        current_user.role, txn.pnv_id, current_user.id,
        current_user.department, txn.pnv.department if txn.pnv else None
    ):
        raise HTTPException(status_code=403, detail="No permission")
    
    quotes = db.query(QuotationHistory).filter(
        QuotationHistory.transaction_id == transaction_id
    ).order_by(QuotationHistory.quoted_at.desc()).all()
    
    return {
        "transaction_id": transaction_id,
        "total_quotes": len(quotes),
        "quotes": [
            {
                "id": q.id,
                "quoted_by": q.quoted_by_name,
                "buy_rate": q.buy_rate,
                "sell_rate": q.sell_rate,
                "status": q.status,
                "countdown": q.countdown_seconds,
                "quoted_at": q.quoted_at.isoformat() if q.quoted_at else None
            }
            for q in quotes
        ]
    }


@router.get("/{transaction_id}/edits")
async def get_edit_history(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📝 Lịch sử chỉnh sửa giao dịch"""
    
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    # Check permission - chỉ PQL xem được
    if current_user.role != UserRole.PQL.value:
        raise HTTPException(status_code=403, detail="Only PQL can view edit history")
    
    edits = db.query(TransactionEdit).filter(
        TransactionEdit.transaction_id == transaction_id
    ).order_by(TransactionEdit.edited_at.desc()).all()
    
    return {
        "transaction_id": transaction_id,
        "total_edits": len(edits),
        "edits": [
            {
                "id": e.id,
                "edited_by": e.edited_by_name,
                "field": e.field_name,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "reason": e.reason,
                "change_type": e.change_type,
                "edited_at": e.edited_at.isoformat() if e.edited_at else None
            }
            for e in edits
        ]
    }
