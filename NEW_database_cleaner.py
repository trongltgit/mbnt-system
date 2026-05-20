"""
🗑️ Module xóa database an toàn
- Backup trước khi xóa
- Chỉ PQL mới có quyền
- Ghi log chi tiết
"""

import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from models import (
    BackupLog, Transaction, QuotationHistory, Message, 
    TransactionEdit, Customer, User, AuditLog
)
from database import SessionLocal
import logging

logger = logging.getLogger(__name__)

class DatabaseCleaner:
    """Xóa database an toàn với backup"""
    
    # Thứ tự xóa (quan trọng vì có FK)
    DELETE_ORDER = [
        'transaction_edits',
        'messages',
        'quotation_history',
        'transactions',
        'customers',
        'exchange_rate_balance',
    ]
    
    # Tables không xóa (user, role, config)
    PROTECTED_TABLES = [
        'users',
        'audit_logs',
        'file_uploads',
        'backup_logs',
        'purposes_sources'
    ]
    
    @staticmethod
    def create_backup(db: Session) -> dict:
        """Tạo backup database trước khi xóa"""
        backup_time = datetime.utcnow()
        backup_dir = Path("backups") / backup_time.strftime("%Y%m%d_%H%M%S")
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        backup_data = {}
        total_records = 0
        
        try:
            # Backup tất cả tables
            for table_name in DatabaseCleaner.DELETE_ORDER:
                if table_name == 'transaction_edits':
                    rows = db.query(TransactionEdit).all()
                    table = 'TransactionEdit'
                elif table_name == 'messages':
                    rows = db.query(Message).all()
                    table = 'Message'
                elif table_name == 'quotation_history':
                    rows = db.query(QuotationHistory).all()
                    table = 'QuotationHistory'
                elif table_name == 'transactions':
                    rows = db.query(Transaction).all()
                    table = 'Transaction'
                elif table_name == 'customers':
                    rows = db.query(Customer).all()
                    table = 'Customer'
                else:
                    continue
                
                # Convert to dict
                data = []
                for row in rows:
                    row_dict = {col.name: getattr(row, col.name) for col in row.__table__.columns}
                    # Convert datetime to string
                    for key, value in row_dict.items():
                        if isinstance(value, datetime):
                            row_dict[key] = value.isoformat()
                    data.append(row_dict)
                
                backup_data[table_name] = data
                total_records += len(data)
                
                # Save to file
                backup_file = backup_dir / f"{table_name}.json"
                with open(backup_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                
                logger.info(f"Backed up {table_name}: {len(data)} records")
            
            # Save metadata
            metadata = {
                "backup_time": backup_time.isoformat(),
                "total_records": total_records,
                "tables": list(backup_data.keys())
            }
            
            with open(backup_dir / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"✅ Backup complete: {backup_dir}")
            
            return {
                "success": True,
                "backup_path": str(backup_dir),
                "total_records": total_records,
                "backup_time": backup_time.isoformat()
            }
        
        except Exception as e:
            logger.error(f"❌ Backup failed: {e}")
            # Xóa backup nếu thất bại
            shutil.rmtree(backup_dir, ignore_errors=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def clear_all(db: Session, user_id: int) -> dict:
        """
        Xóa tất cả dữ liệu giao dịch
        ⚠️ Chỉ PQL mới có quyền
        """
        try:
            # 1. Tạo backup trước
            backup_result = DatabaseCleaner.create_backup(db)
            if not backup_result["success"]:
                return {
                    "success": False,
                    "error": f"Backup failed: {backup_result.get('error', 'Unknown error')}"
                }
            
            # 2. Xóa dữ liệu theo thứ tự
            delete_counts = {}
            
            for table_name in DatabaseCleaner.DELETE_ORDER:
                try:
                    if table_name == 'transaction_edits':
                        count = db.query(TransactionEdit).count()
                        db.query(TransactionEdit).delete()
                    elif table_name == 'messages':
                        count = db.query(Message).count()
                        db.query(Message).delete()
                    elif table_name == 'quotation_history':
                        count = db.query(QuotationHistory).count()
                        db.query(QuotationHistory).delete()
                    elif table_name == 'transactions':
                        count = db.query(Transaction).count()
                        db.query(Transaction).delete()
                    elif table_name == 'customers':
                        count = db.query(Customer).count()
                        db.query(Customer).delete()
                    else:
                        continue
                    
                    delete_counts[table_name] = count
                    db.commit()
                    logger.info(f"✅ Deleted {table_name}: {count} records")
                
                except Exception as e:
                    db.rollback()
                    logger.error(f"❌ Error deleting {table_name}: {e}")
                    raise
            
            # 3. Ghi log vào backup_logs
            backup_log = BackupLog(
                backup_type="full",
                backup_path=backup_result["backup_path"],
                backup_size=0,  # Có thể tính sau
                records_backed_up=backup_result["total_records"],
                created_by=user_id,
                notes="Database cleared - Full backup created"
            )
            db.add(backup_log)
            
            # 4. Ghi audit log
            audit_log = AuditLog(
                user_id=user_id,
                action="clear_database",
                resource_type="database",
                details=json.dumps({
                    "deleted_tables": delete_counts,
                    "backup_path": backup_result["backup_path"],
                    "total_records_deleted": sum(delete_counts.values())
                })
            )
            db.add(audit_log)
            db.commit()
            
            return {
                "success": True,
                "message": "Database cleared successfully",
                "backup_path": backup_result["backup_path"],
                "deleted_records": delete_counts,
                "total_deleted": sum(delete_counts.values())
            }
        
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Clear database error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def clear_table(db: Session, table_name: str, user_id: int) -> dict:
        """Xóa một bảng cụ thể"""
        
        if table_name in DatabaseCleaner.PROTECTED_TABLES:
            return {
                "success": False,
                "error": f"Cannot delete protected table: {table_name}"
            }
        
        try:
            count = 0
            
            if table_name == 'transactions':
                count = db.query(Transaction).count()
                db.query(Transaction).delete()
            elif table_name == 'messages':
                count = db.query(Message).count()
                db.query(Message).delete()
            elif table_name == 'quotation_history':
                count = db.query(QuotationHistory).count()
                db.query(QuotationHistory).delete()
            else:
                return {"success": False, "error": f"Unknown table: {table_name}"}
            
            db.commit()
            
            # Ghi log
            audit_log = AuditLog(
                user_id=user_id,
                action=f"clear_table_{table_name}",
                resource_type="database",
                details=f"Cleared {count} records from {table_name}"
            )
            db.add(audit_log)
            db.commit()
            
            logger.info(f"✅ Cleared {table_name}: {count} records")
            
            return {
                "success": True,
                "table": table_name,
                "records_deleted": count
            }
        
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Error clearing {table_name}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    @staticmethod
    def list_backups() -> list:
        """Liệt kê tất cả backups"""
        backup_root = Path("backups")
        if not backup_root.exists():
            return []
        
        backups = []
        for backup_dir in sorted(backup_root.iterdir(), reverse=True):
            if backup_dir.is_dir():
                metadata_file = backup_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                    backups.append({
                        "path": str(backup_dir),
                        "time": metadata.get("backup_time"),
                        "records": metadata.get("total_records"),
                        "tables": metadata.get("tables")
                    })
        
        return backups
    
    @staticmethod
    def restore_backup(backup_path: str) -> dict:
        """Restore từ backup (future feature)"""
        # TODO: Implement restore functionality
        return {
            "success": False,
            "error": "Restore feature not yet implemented"
        }
