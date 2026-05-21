"""
💬 Message Router - Chat, Q&A, Quotation messages
Thêm: Tên người nhận, phòng ban, hiển thị Q&A
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import logging

from database import SessionLocal
from models import User, Message, MessageType, Transaction, AuditLog
from realtime_handler import RealtimeEventEmitter, ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/messages",
    tags=["messages"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = None) -> User:
    """Get current user"""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    db = SessionLocal()
    user = db.query(User).filter(User.username == token).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user


@router.get("/")
async def list_messages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    unread_only: bool = False,
    limit: int = 50
):
    """
    📬 Liệt kê tin nhắn
    
    🆕 Format: "{Tên} - {Vai trò} - {Phòng ban}"
    VD: "Hoàng Văn E - PQL - Kế toán"
    """
    
    query = db.query(Message)
    
    # Filter by current user role
    if current_user.role == "pql":
        # PQL xem tất cả
        pass
    elif current_user.role == "bgd":
        # BGD xem phòng của mình
        query = query.filter(
            Message.recipient_department == current_user.department
        )
    else:
        # PNV/PGD chỉ xem của mình
        query = query.filter(
            (Message.recipient_id == current_user.id) |
            (Message.recipient_ids.contains(str(current_user.id)))
        )
    
    if unread_only:
        query = query.filter(Message.is_read == False)
    
    messages = query.order_by(Message.created_at.desc()).limit(limit).all()
    
    return {
        "total": len(messages),
        "messages": [
            {
                "id": msg.id,
                "sender": {
                    "id": msg.sender.id,
                    "name": msg.sender.full_name,
                    "role": msg.sender.role,
                    "department": msg.sender.department,
                    # 🆕 Formatted display name
                    "display_name": f"{msg.sender.full_name} - {msg.sender.role.upper()} - {msg.sender.department}"
                },
                "recipient": {
                    "id": msg.recipient_id,
                    "name": msg.recipient_name,  # 🆕
                    "role": msg.recipient_role,  # 🆕
                    "department": msg.recipient_department
                },
                "message_type": msg.message_type,
                "content": msg.content,
                # 🆕 Q&A fields
                "question_content": msg.question_content,
                "answer_content": msg.answer_content,
                "is_answered": msg.is_answered,
                "is_read": msg.is_read,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "answered_at": msg.answered_at.isoformat() if msg.answered_at else None,
                "transaction_id": msg.transaction_id
            }
            for msg in messages
        ]
    }


@router.get("/{message_id}")
async def get_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📨 Lấy 1 tin nhắn chi tiết"""
    
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check permission
    if current_user.role != "pql" and current_user.id != msg.recipient_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    
    # Mark as read
    if not msg.is_read and msg.recipient_id == current_user.id:
        msg.is_read = True
        db.commit()
    
    return {
        "id": msg.id,
        "sender": {
            "id": msg.sender.id,
            "name": msg.sender.full_name,
            "role": msg.sender.role,
            "department": msg.sender.department,
            "display_name": f"{msg.sender.full_name} - {msg.sender.role.upper()} - {msg.sender.department}"
        },
        "recipient": {
            "id": msg.recipient_id,
            "name": msg.recipient_name,
            "role": msg.recipient_role,
            "department": msg.recipient_department
        },
        "message_type": msg.message_type,
        "content": msg.content,
        "question_content": msg.question_content,
        "answer_content": msg.answer_content,
        "is_answered": msg.is_answered,
        "is_read": msg.is_read,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "answered_at": msg.answered_at.isoformat() if msg.answered_at else None,
        "transaction_id": msg.transaction_id
    }


@router.post("/send")
async def send_message(
    recipient_id: int,
    recipient_name: str,
    recipient_role: str,
    content: str,
    message_type: str = "chat",  # chat, quotation, qa
    question_content: str = None,  # 🆕 Nội dung câu hỏi (nếu là Q&A)
    recipient_department: str = None,
    transaction_id: int = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💬 Gửi tin nhắn
    
    🆕 Bắt buộc: recipient_name, recipient_role
    VD: Hoàng Văn E, PQL
    """
    
    # Validate
    if not recipient_name or not recipient_role:
        raise HTTPException(
            status_code=400,
            detail="recipient_name and recipient_role are required"
        )
    
    recipient = db.query(User).filter(User.id == recipient_id).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    # Create message
    message = Message(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        recipient_name=recipient_name,  # 🆕
        recipient_role=recipient_role,  # 🆕
        recipient_department=recipient_department or recipient.department,
        message_type=message_type,
        content=content,
        question_content=question_content,  # 🆕
        transaction_id=transaction_id
    )
    
    db.add(message)
    db.commit()
    
    # 🆕 Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="send_message",
        resource_type="message",
        resource_id=message.id,
        details=f"Sent {message_type} to {recipient_name}"
    )
    db.add(audit)
    db.commit()
    
    # Emit realtime event
    await RealtimeEventEmitter.message_sent(
        sender_id=current_user.id,
        recipient_id=recipient_id,
        message_data={
            "id": message.id,
            "sender": current_user.full_name,
            "recipient": recipient_name,
            "content": content,
            "type": message_type
        }
    )
    
    logger.info(f"✅ Message sent: {current_user.username} -> {recipient_name}")
    
    return {
        "success": True,
        "message_id": message.id,
        "sent_to": recipient_name,
        "timestamp": message.created_at.isoformat() if message.created_at else None
    }


@router.put("/{message_id}/reply")
async def reply_message(
    message_id: int,
    answer_content: str,  # 🆕 Nội dung câu trả lời
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ✏️ Trả lời câu hỏi
    🆕 Thêm nội dung trả lời vào message ban đầu
    """
    
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check permission - chỉ người nhận mới trả lời
    if current_user.id != msg.recipient_id:
        raise HTTPException(status_code=403, detail="Only recipient can reply")
    
    # Update message
    msg.answer_content = answer_content  # 🆕
    msg.is_answered = True  # 🆕
    msg.answered_at = datetime.utcnow()  # 🆕
    
    db.commit()
    
    logger.info(f"✅ Message {message_id} replied by {current_user.username}")
    
    return {
        "success": True,
        "message_id": message_id,
        "is_answered": True,
        "answered_at": msg.answered_at.isoformat() if msg.answered_at else None
    }


@router.put("/{message_id}/mark-as-read")
async def mark_as_read(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """✅ Đánh dấu đã đọc"""
    
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    msg.is_read = True
    db.commit()
    
    return {"success": True, "is_read": True}


@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🗑️ Xóa tin nhắn"""
    
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Check permission
    if current_user.id != msg.sender_id and current_user.role != "pql":
        raise HTTPException(status_code=403, detail="Permission denied")
    
    db.delete(msg)
    db.commit()
    
    return {"success": True, "message_id": message_id}


@router.get("/count/unread")
async def count_unread(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📊 Đếm tin nhắn chưa đọc"""
    
    unread_count = db.query(Message).filter(
        Message.recipient_id == current_user.id,
        Message.is_read == False
    ).count()
    
    return {
        "unread_count": unread_count,
        "user_id": current_user.id
    }
