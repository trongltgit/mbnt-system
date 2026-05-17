from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime
from database import get_db
from models import User, Message, Transaction, UserRole, MessageType
from schemas import MessageCreate, MessageResponse
from auth import get_current_user

router = APIRouter(prefix="/api/messages", tags=["messages"])

@router.post("/send", response_model=dict)
def send_message(
    request: MessageCreate,
    sender: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send message (chat or quotation)"""
    # Validate recipient department/users
    if request.message_type == MessageType.QUOTATION.value:
        # Quotation must have transaction_id
        if not request.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quotation message must reference a transaction"
            )
        
        # Get transaction to verify
        transaction = db.query(Transaction).filter(
            Transaction.id == request.transaction_id
        ).first()
        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )
    
    # Create message
    message = Message(
        sender_id=sender.id,
        recipient_department=request.recipient_department,
        recipient_ids=request.recipient_ids,
        transaction_id=request.transaction_id,
        message_type=request.message_type,
        content=request.content,
        is_read=False
    )
    
    db.add(message)
    db.commit()
    db.refresh(message)
    
    return {
        "id": message.id,
        "message": "Message sent successfully",
        "created_at": message.created_at
    }

@router.get("/inbox")
def get_inbox(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    skip: int = Query(0),
    limit: int = Query(50),
    unread_only: bool = Query(False),
    message_type: str = Query(None)
):
    """Get messages for current user"""
    query = db.query(Message).filter(
        # Messages sent to user's department or specifically to user
        (Message.recipient_department == current_user.department) |
        (Message.recipient_ids.like(f"%{current_user.id}%"))
    )
    
    if unread_only:
        query = query.filter(Message.is_read == False)
    
    if message_type:
        query = query.filter(Message.message_type == message_type)
    
    # Order by newest first
    total = query.count()
    messages = query.order_by(Message.created_at.desc()).offset(skip).limit(limit).all()
    
    result = []
    for msg in messages:
        sender = db.query(User).filter(User.id == msg.sender_id).first()
        result.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "sender_username": sender.username if sender else "Unknown",
            "message_type": msg.message_type,
            "content": msg.content,
            "created_at": msg.created_at,
            "is_read": msg.is_read,
            "transaction_id": msg.transaction_id
        })
    
    return {
        "total": total,
        "unread_count": query.filter(Message.is_read == False).count(),
        "messages": result
    }

@router.post("/mark-read/{message_id}")
def mark_message_read(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Mark message as read"""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    message.is_read = True
    db.commit()
    
    return {"message": "Message marked as read"}

@router.post("/mark-all-read")
def mark_all_messages_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    message_type: str = None
):
    """Mark all unread messages as read for current user"""
    query = db.query(Message).filter(
        (Message.recipient_department == current_user.department) |
        (Message.recipient_ids.like(f"%{current_user.id}%")),
        Message.is_read == False
    )
    
    if message_type:
        query = query.filter(Message.message_type == message_type)
    
    count = query.count()
    query.update({"is_read": True})
    db.commit()
    
    return {"message": f"Marked {count} messages as read"}

@router.get("/unread-count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get count of unread messages by type"""
    total_unread = db.query(Message).filter(
        (Message.recipient_department == current_user.department) |
        (Message.recipient_ids.like(f"%{current_user.id}%")),
        Message.is_read == False
    ).count()
    
    quotation_unread = db.query(Message).filter(
        (Message.recipient_department == current_user.department) |
        (Message.recipient_ids.like(f"%{current_user.id}%")),
        Message.is_read == False,
        Message.message_type == MessageType.QUOTATION.value
    ).count()
    
    chat_unread = db.query(Message).filter(
        (Message.recipient_department == current_user.department) |
        (Message.recipient_ids.like(f"%{current_user.id}%")),
        Message.is_read == False,
        Message.message_type == MessageType.CHAT.value
    ).count()
    
    return {
        "total": total_unread,
        "quotations": quotation_unread,
        "chats": chat_unread
    }

@router.get("/transaction/{transaction_id}")
def get_transaction_messages(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all messages for a specific transaction"""
    # Verify user has access to this transaction
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    # Check access: PNV (sender), PQL (recipient), or BGD managing PNV
    if current_user.role == UserRole.PNV.value:
        if transaction.pnv_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this transaction"
            )
    elif current_user.role == UserRole.BGD.value:
        # Check if managing this PNV
        from models import BGDManagement
        management = db.query(BGDManagement).filter(
            BGDManagement.bgd_id == current_user.id,
            BGDManagement.pnv_user_id == transaction.pnv_id
        ).first()
        if not management:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this transaction"
            )
    
    # Get messages
    messages = db.query(Message).filter(
        Message.transaction_id == transaction_id
    ).order_by(Message.created_at).all()
    
    result = []
    for msg in messages:
        sender = db.query(User).filter(User.id == msg.sender_id).first()
        result.append({
            "id": msg.id,
            "sender_id": msg.sender_id,
            "sender_username": sender.username if sender else "Unknown",
            "sender_name": sender.full_name if sender else "Unknown",
            "message_type": msg.message_type,
            "content": msg.content,
            "created_at": msg.created_at,
            "is_read": msg.is_read
        })
    
    return result

@router.delete("/messages/{message_id}")
def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete message (sender only)"""
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found"
        )
    
    if message.sender_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own messages"
        )
    
    db.delete(message)
    db.commit()
    
    return {"message": "Message deleted"}
