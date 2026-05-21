"""
🛡️ Admin Router - Quản lý hệ thống
Chỉ PQL mới có quyền xóa database
"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from database import SessionLocal
from models import User, UserRole, AuditLog
from database_cleaner import DatabaseCleaner
from realtime_handler import RealtimeEventEmitter
from permissions import PermissionManager, check_role

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = None) -> User:
    """Get current user from token (simplified)"""
    # TODO: Implement real JWT validation
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
    return {"status": "healthy", "service": "admin"}


@router.get("/users")
@check_role(UserRole.PQL.value, UserRole.BGD.value)
async def list_users(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📋 Liệt kê tất cả users (PQL, BGD only)"""
    users = db.query(User).all()
    return {
        "total": len(users),
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role,
                "department": u.department,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat() if u.created_at else None
            }
            for u in users
        ]
    }


@router.post("/users")
@check_role(UserRole.PQL.value)
async def create_user(
    username: str,
    email: str,
    full_name: str,
    role: str,
    department: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """👤 Tạo user mới (PQL only)"""
    
    # Check username exists
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    new_user = User(
        username=username,
        email=email,
        full_name=full_name,
        role=role,
        department=department,
        is_active=True
    )
    
    db.add(new_user)
    db.commit()
    
    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="create_user",
        resource_type="user",
        resource_id=new_user.id,
        details=f"Created user: {username}"
    )
    db.add(audit)
    db.commit()
    
    logger.info(f"✅ Created user: {username}")
    
    return {
        "success": True,
        "user_id": new_user.id,
        "username": username
    }


@router.put("/users/{user_id}")
@check_role(UserRole.PQL.value)
async def update_user(
    user_id: int,
    full_name: str = None,
    department: str = None,
    is_active: bool = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """✏️ Cập nhật user (PQL only)"""
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if full_name:
        user.full_name = full_name
    if department:
        user.department = department
    if is_active is not None:
        user.is_active = is_active
    
    db.commit()
    
    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="update_user",
        resource_type="user",
        resource_id=user_id,
        details=f"Updated user: {user.username}"
    )
    db.add(audit)
    db.commit()
    
    return {"success": True, "user_id": user_id}


@router.delete("/users/{user_id}")
@check_role(UserRole.PQL.value)
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """🗑️ Xóa user (PQL only)"""
    
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    db.delete(user)
    db.commit()
    
    # Audit log
    audit = AuditLog(
        user_id=current_user.id,
        action="delete_user",
        resource_type="user",
        resource_id=user_id,
        details=f"Deleted user: {user.username}"
    )
    db.add(audit)
    db.commit()
    
    return {"success": True, "user_id": user_id}


# 🆕 DELETE DATABASE - CHÍNH FEATURE
@router.post("/clear-database")
@check_role(UserRole.PQL.value)
async def clear_database(
    confirm: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None
):
    """
    ⚠️ DANGER ZONE ⚠️
    Xóa tất cả dữ liệu giao dịch (BACKUP will be created)
    Chỉ PQL mới có quyền
    
    Parameters:
    - confirm: phải là True để xóa
    
    Returns:
    - backup_path: đường dẫn backup
    - deleted_records: số record xóa
    """
    
    # Double check
    PermissionManager.check_delete_database(current_user.role)
    
    if not confirm:
        return {
            "success": False,
            "error": "Confirmation required. Set confirm=true",
            "warning": "⚠️ This action will delete ALL transaction data!"
        }
    
    try:
        logger.warning(f"🔥 PQL {current_user.username} is deleting database...")
        
        # Thực hiện xóa database
        result = DatabaseCleaner.clear_all(db, current_user.id)
        
        if result["success"]:
            # Emit realtime event
            await RealtimeEventEmitter.database_cleared(current_user.full_name)
            
            logger.warning(f"✅ Database cleared by {current_user.username}")
            logger.info(f"   Backup saved at: {result['backup_path']}")
            logger.info(f"   Total deleted: {result['total_deleted']} records")
            
            return {
                "success": True,
                "message": "Database cleared successfully",
                "backup_path": result["backup_path"],
                "deleted_records": result["deleted_records"],
                "total_deleted": result["total_deleted"],
                "cleared_by": current_user.full_name,
                "cleared_at": db.query(AuditLog).filter(
                    AuditLog.action == "clear_database"
                ).order_by(AuditLog.created_at.desc()).first().created_at.isoformat()
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error")
            }
    
    except Exception as e:
        logger.error(f"❌ Error clearing database: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/clear-table/{table_name}")
@check_role(UserRole.PQL.value)
async def clear_table(
    table_name: str,
    confirm: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ⚠️ Xóa một bảng cụ thể
    Chỉ PQL
    
    Parameters:
    - table_name: transactions, messages, quotation_history
    - confirm: phải là True
    """
    
    PermissionManager.check_delete_database(current_user.role)
    
    if not confirm:
        return {
            "success": False,
            "error": "Confirmation required"
        }
    
    result = DatabaseCleaner.clear_table(db, table_name, current_user.id)
    
    if result["success"]:
        logger.warning(f"✅ Cleared {table_name}: {result['records_deleted']} records")
    
    return result


@router.get("/backups")
@check_role(UserRole.PQL.value)
async def list_backups(current_user: User = Depends(get_current_user)):
    """📦 Liệt kê tất cả backups (PQL only)"""
    backups = DatabaseCleaner.list_backups()
    
    return {
        "total": len(backups),
        "backups": backups
    }


@router.get("/audit-logs")
@check_role(UserRole.PQL.value, UserRole.BGD.value)
async def get_audit_logs(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📝 Xem audit logs (PQL, BGD only)"""
    logs = db.query(AuditLog).order_by(
        AuditLog.created_at.desc()
    ).limit(limit).all()
    
    return {
        "total": len(logs),
        "logs": [
            {
                "id": log.id,
                "user": db.query(User).filter(User.id == log.user_id).first().full_name if log.user_id else "System",
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None
            }
            for log in logs
        ]
    }


@router.get("/stats")
@check_role(UserRole.PQL.value, UserRole.BGD.value)
async def system_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """📊 Thống kê hệ thống (PQL, BGD only)"""
    
    from models import Transaction, Message, User, Customer
    
    total_users = db.query(User).count()
    total_customers = db.query(Customer).count()
    total_transactions = db.query(Transaction).count()
    total_messages = db.query(Message).count()
    
    return {
        "total_users": total_users,
        "total_customers": total_customers,
        "total_transactions": total_transactions,
        "total_messages": total_messages
    }
