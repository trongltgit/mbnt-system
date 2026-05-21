"""
📊 Report Router - Báo cáo & Blotter
- Export báo cáo (.xlsx, .csv, .pdf)
- Real-time blotter updates
- Phân quyền: PNV thấy phòng mình, PQL thấy tất cả
- PNV không thấy system_rate
"""

from fastapi import APIRouter, Depends, HTTPException, FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import io
import logging

from database import SessionLocal
from models import (
    Transaction, Message, User, UserRole, TransactionEdit, 
    AuditLog, QuotationHistory
)
from permissions import PermissionManager, check_role
from realtime_handler import RealtimeEventEmitter
from excel_export import ExcelExporter, CSVExporter, PDFExporter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reports",
    tags=["reports"]
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
    return {"status": "healthy", "service": "reports"}


# 🆕 EXPORT ENDPOINT
@router.post("/export/{format}")
async def export_report(
    format: str,  # xlsx, csv, pdf
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📊 Xuất báo cáo
    
    🆕 Format: xlsx, csv, pdf
    Phân quyền: PNV thấy phòng mình, PQL thấy tất cả
    PNV không thấy system_rate
    """
    
    if format not in ["xlsx", "csv", "pdf"]:
        raise HTTPException(status_code=400, detail="Invalid format. Use: xlsx, csv, pdf")
    
    # Get transactions based on role
    query = db.query(Transaction)
    
    if current_user.role == UserRole.PNV.value:
        # PNV: chỉ xem của mình
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        # PGD: xem của phòng mình
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    # PQL/BGD: thấy tất cả
    
    transactions = query.all()
    
    # Get related data
    messages = db.query(Message).all()
    edits = db.query(TransactionEdit).all() if current_user.role == UserRole.PQL.value else []
    
    try:
        if format == "xlsx":
            logger.info(f"📊 Exporting XLSX report by {current_user.username}")
            
            content = ExcelExporter.to_xlsx(
                transactions, messages, edits, 
                current_user.role, 
                current_user.id, 
                current_user.department
            )
            filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        
        elif format == "csv":
            logger.info(f"📊 Exporting CSV report by {current_user.username}")
            
            content = CSVExporter.to_csv(
                transactions,
                current_user.role,
                current_user.id,
                current_user.department
            )
            filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
            media_type = "text/csv"
        
        elif format == "pdf":
            logger.info(f"📊 Exporting PDF report by {current_user.username}")
            
            content = PDFExporter.to_pdf(
                transactions,
                current_user.role,
                current_user.id,
                current_user.department
            )
            filename = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
            media_type = "application/pdf"
        
        # Ghi audit log
        audit = AuditLog(
            user_id=current_user.id,
            action="export_report",
            resource_type="report",
            resource_id=None,
            details=f"Exported {format} report. Records: {len(transactions)}"
        )
        db.add(audit)
        db.commit()
        
        logger.info(f"✅ Export completed: {filename}")
        
        return FileResponse(
            io.BytesIO(content),
            filename=filename,
            media_type=media_type
        )
    
    except Exception as e:
        logger.error(f"❌ Export error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# 🆕 BLOTTER ENDPOINT - Real-time update
@router.get("/blotter")
async def get_blotter(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📊 Blotter - Real-time update
    
    🆕 Update real-time theo role
    PNV không thấy system_rate
    """
    
    query = db.query(Transaction).order_by(Transaction.created_at.desc())
    
    if current_user.role == UserRole.PNV.value:
        # PNV: chỉ xem của mình
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        # PGD: xem của phòng mình
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    # PQL/BGD: thấy tất cả
    
    transactions = query.limit(limit).all()
    
    # Format blotter data
    blotter_data = []
    for txn in transactions:
        item = {
            "id": txn.id,
            "transaction_no": txn.transaction_no,
            "date": txn.transaction_date.isoformat() if txn.transaction_date else None,
            "customer": txn.customer.customer_name if txn.customer else "",
            "direction": txn.direction.upper(),
            "currency": txn.currency_code,
            "amount": txn.amount,
            "buy_rate": txn.buy_rate,
            "sell_rate": txn.sell_rate,
            "profit": txn.profit,
            "status": txn.status,
            "pnv": txn.pnv.full_name if txn.pnv else "",
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
            "accepted_at": txn.accepted_at.isoformat() if txn.accepted_at else None
        }
        
        # Hide system_rate from PNV
        if PermissionManager.can_see_system_rate(current_user.role):
            item["system_buy_rate"] = txn.system_buy_rate
            item["system_sell_rate"] = txn.system_sell_rate
        
        # Apply permission filtering
        item = PermissionManager.filter_sensitive_fields(item, current_user.role)
        
        blotter_data.append(item)
    
    return {
        "count": len(blotter_data),
        "data": blotter_data,
        "last_updated": datetime.utcnow().isoformat(),
        "limit": limit
    }


@router.get("/summary")
async def get_summary(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📈 Báo cáo tóm tắt
    - Tổng giao dịch
    - Tổng lãi/lỗ
    - Giao dịch theo trạng thái
    """
    
    query = db.query(Transaction)
    
    if current_user.role == UserRole.PNV.value:
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    
    transactions = query.all()
    
    # Calculate summary
    total_transactions = len(transactions)
    total_profit = sum(t.profit or 0 for t in transactions)
    accepted_count = len([t for t in transactions if t.status == "accepted"])
    rejected_count = len([t for t in transactions if t.status == "rejected"])
    pending_count = len([t for t in transactions if t.status == "pending"])
    
    # Calculate by currency
    currency_summary = {}
    for txn in transactions:
        curr = txn.currency_code
        if curr not in currency_summary:
            currency_summary[curr] = {
                "count": 0,
                "amount": 0,
                "profit": 0
            }
        currency_summary[curr]["count"] += 1
        currency_summary[curr]["amount"] += txn.amount or 0
        currency_summary[curr]["profit"] += txn.profit or 0
    
    return {
        "total_transactions": total_transactions,
        "total_profit": total_profit,
        "accepted": accepted_count,
        "rejected": rejected_count,
        "pending": pending_count,
        "by_currency": currency_summary,
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/daily")
async def get_daily_report(
    date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📅 Báo cáo theo ngày
    date format: YYYY-MM-DD (default: today)
    """
    
    if not date:
        from datetime import date as date_class
        date = date_class.today().isoformat()
    
    # Parse date
    try:
        target_date = datetime.fromisoformat(date).date()
    except:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    query = db.query(Transaction).filter(
        Transaction.transaction_date >= f"{target_date}T00:00:00",
        Transaction.transaction_date <= f"{target_date}T23:59:59"
    )
    
    if current_user.role == UserRole.PNV.value:
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    
    transactions = query.all()
    
    # Build report
    report_data = []
    total_profit = 0
    
    for txn in transactions:
        item = {
            "transaction_no": txn.transaction_no,
            "time": txn.transaction_date.strftime("%H:%M:%S") if txn.transaction_date else "",
            "customer": txn.customer.customer_name if txn.customer else "",
            "direction": txn.direction.upper(),
            "currency": txn.currency_code,
            "amount": txn.amount,
            "buy_rate": txn.buy_rate,
            "sell_rate": txn.sell_rate,
            "profit": txn.profit,
            "status": txn.status
        }
        
        if PermissionManager.can_see_system_rate(current_user.role):
            item["system_buy_rate"] = txn.system_buy_rate
            item["system_sell_rate"] = txn.system_sell_rate
        
        report_data.append(item)
        total_profit += txn.profit or 0
    
    return {
        "date": date,
        "total_transactions": len(transactions),
        "total_profit": total_profit,
        "transactions": report_data,
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/period")
async def get_period_report(
    start_date: str,
    end_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📊 Báo cáo theo kỳ (từ ngày này đến ngày khác)
    Format: YYYY-MM-DD
    """
    
    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    query = db.query(Transaction).filter(
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end
    )
    
    if current_user.role == UserRole.PNV.value:
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    
    transactions = query.all()
    
    # Group by currency
    by_currency = {}
    for txn in transactions:
        curr = txn.currency_code
        if curr not in by_currency:
            by_currency[curr] = {
                "count": 0,
                "amount": 0,
                "profit": 0,
                "accepted": 0,
                "rejected": 0
            }
        by_currency[curr]["count"] += 1
        by_currency[curr]["amount"] += txn.amount or 0
        by_currency[curr]["profit"] += txn.profit or 0
        
        if txn.status == "accepted":
            by_currency[curr]["accepted"] += 1
        elif txn.status == "rejected":
            by_currency[curr]["rejected"] += 1
    
    total_profit = sum(t.profit or 0 for t in transactions)
    
    return {
        "period": f"{start_date} to {end_date}",
        "total_transactions": len(transactions),
        "total_profit": total_profit,
        "by_currency": by_currency,
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/performance/{period}")
async def get_performance_report(
    period: str,  # daily, weekly, monthly
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📈 Báo cáo hiệu suất
    period: daily, weekly, monthly
    """
    
    if period not in ["daily", "weekly", "monthly"]:
        raise HTTPException(status_code=400, detail="Invalid period. Use: daily, weekly, monthly")
    
    query = db.query(Transaction)
    
    if current_user.role == UserRole.PNV.value:
        query = query.filter(Transaction.pnv_id == current_user.id)
    elif current_user.role == UserRole.PGD.value:
        query = query.filter(
            Transaction.pnv.has(User.department == current_user.department)
        )
    
    transactions = query.all()
    
    # Group by period
    grouped = {}
    for txn in transactions:
        if txn.transaction_date:
            if period == "daily":
                key = txn.transaction_date.strftime("%Y-%m-%d")
            elif period == "weekly":
                key = txn.transaction_date.strftime("%Y-W%U")
            else:  # monthly
                key = txn.transaction_date.strftime("%Y-%m")
            
            if key not in grouped:
                grouped[key] = {
                    "count": 0,
                    "profit": 0,
                    "accepted": 0,
                    "rejected": 0
                }
            
            grouped[key]["count"] += 1
            grouped[key]["profit"] += txn.profit or 0
            
            if txn.status == "accepted":
                grouped[key]["accepted"] += 1
            elif txn.status == "rejected":
                grouped[key]["rejected"] += 1
    
    return {
        "period_type": period,
        "data": grouped,
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/edit-log")
@check_role(UserRole.PQL.value)
async def get_edit_log(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    📝 Lịch sử chỉnh sửa (PQL only)
    
    Hiển thị tất cả chỉnh sửa trên hệ thống
    Ghi chú: ai chỉnh sửa, cái gì, lúc nào, lý do
    """
    
    edits = db.query(TransactionEdit).order_by(
        TransactionEdit.edited_at.desc()
    ).limit(limit).all()
    
    return {
        "total": len(edits),
        "edits": [
            {
                "id": e.id,
                "transaction_id": e.transaction_id,
                "edited_by": e.edited_by_name,
                "field": e.field_name,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "reason": e.reason,
                "change_type": e.change_type,
                "edited_at": e.edited_at.isoformat() if e.edited_at else None
            }
            for e in edits
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/audit-trail")
@check_role(UserRole.PQL.value, UserRole.UserRole.BGD.value)
async def get_audit_trail(
    resource_type: Optional[str] = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    🔍 Audit trail (PQL, BGD only)
    
    Theo dõi tất cả hoạt động của hệ thống
    """
    
    query = db.query(AuditLog)
    
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    
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
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/quote-status")
async def get_quote_status_report(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    💬 Báo cáo trạng thái chào giá
    - Đang chờ
    - Chấp nhận
    - Từ chối
    - Bị gián đoạn
    """
    
    query = db.query(QuotationHistory)
    
    # Count by status
    active = query.filter(QuotationHistory.status == "active").count()
    accepted = query.filter(QuotationHistory.status == "accepted").count()
    rejected = query.filter(QuotationHistory.status == "rejected").count()
    interrupted = query.filter(QuotationHistory.status == "interrupted").count()
    
    return {
        "active": active,
        "accepted": accepted,
        "rejected": rejected,
        "interrupted": interrupted,
        "total": active + accepted + rejected + interrupted,
        "generated_at": datetime.utcnow().isoformat()
    }
