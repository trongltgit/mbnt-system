"""
🔐 Module quản lý phân quyền (Permissions)
Định nghĩa quyền hạn cho từng role: PQL, PNV, BGD, PGD
"""

from functools import wraps
from fastapi import HTTPException, status
from models import UserRole

class PermissionManager:
    """Quản lý phân quyền dựa trên role"""
    
    # Define what each role can do
    PERMISSIONS = {
        UserRole.PQL.value: {
            "view_all_transactions": True,
            "edit_transaction": True,
            "edit_system_rate": True,
            "delete_database": True,
            "export_report": True,
            "view_all_blotter": True,
            "edit_with_reason": True,  # Phải ghi lý do
            "manage_quotes": True,
            "view_customer_secret": True,  # Xem tỷ giá hệ thống
        },
        UserRole.PNV.value: {
            "view_own_transactions": True,
            "view_quote": True,
            "accept_quote": True,
            "reject_quote": True,
            "export_report": True,
            "view_own_blotter": True,
            "view_customer_secret": False,  # ❌ Không xem tỷ giá hệ thống
        },
        UserRole.BGD.value: {
            "view_all_transactions": True,
            "view_all_blotter": True,
            "view_all_reports": True,
            "view_customer_secret": True,
            "export_report": True,
        },
        UserRole.PGD.value: {
            "view_group_transactions": True,  # Xem của nhóm phòng
            "view_group_blotter": True,
            "view_group_reports": True,
            "export_report": True,
            "view_customer_secret": True,
        }
    }
    
    @staticmethod
    def has_permission(user_role: str, permission: str) -> bool:
        """Kiểm tra user có quyền không"""
        if user_role not in PermissionManager.PERMISSIONS:
            return False
        return PermissionManager.PERMISSIONS[user_role].get(permission, False)
    
    @staticmethod
    def check_delete_database(user_role: str):
        """Chỉ PQL mới có quyền xóa database"""
        if user_role != UserRole.PQL.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ PQL mới có quyền xóa database"
            )
    
    @staticmethod
    def check_edit_system_rate(user_role: str):
        """Chỉ PQL mới chỉnh sửa tỷ giá hệ thống"""
        if user_role != UserRole.PQL.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ PQL mới có quyền chỉnh sửa tỷ giá hệ thống"
            )
    
    @staticmethod
    def can_view_transaction(user_role: str, transaction_owner_id: int, current_user_id: int, 
                            current_user_department: str = None, owner_department: str = None) -> bool:
        """
        Kiểm tra user có quyền xem giao dịch không
        - PQL: xem tất cả ✅
        - PNV: chỉ xem của mình ✅
        - BGD: xem tất cả ✅
        - PGD: xem của nhóm phòng ✅
        """
        if user_role == UserRole.PQL.value or user_role == UserRole.BGD.value:
            return True
        
        if user_role == UserRole.PNV.value:
            return current_user_id == transaction_owner_id
        
        if user_role == UserRole.PGD.value:
            return current_user_department == owner_department
        
        return False
    
    @staticmethod
    def can_edit_transaction(user_role: str) -> bool:
        """Chỉ PQL mới chỉnh sửa giao dịch"""
        return user_role == UserRole.PQL.value
    
    @staticmethod
    def can_see_system_rate(user_role: str) -> bool:
        """
        PNV không xem thấy tỷ giá hệ thống
        PQL, BGD, PGD: xem được
        """
        return user_role != UserRole.PNV.value
    
    @staticmethod
    def filter_sensitive_fields(transaction_dict: dict, user_role: str) -> dict:
        """
        Lọc các trường nhạy cảm dựa trên role
        PNV: không thấy system_buy_rate, system_sell_rate
        """
        if user_role == UserRole.PNV.value:
            transaction_dict.pop('system_buy_rate', None)
            transaction_dict.pop('system_sell_rate', None)
            transaction_dict.pop('last_edited_by', None)
            transaction_dict.pop('last_edited_at', None)
        return transaction_dict


def check_permission_decorator(permission: str):
    """
    Decorator để check quyền
    Usage: @check_permission_decorator("delete_database")
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if current_user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unauthorized"
                )
            
            if not PermissionManager.has_permission(current_user.role, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Bạn không có quyền: {permission}"
                )
            
            return await func(*args, current_user=current_user, **kwargs)
        
        return wrapper
    return decorator


def check_role(*allowed_roles: str):
    """
    Decorator kiểm tra role
    Usage: @check_role(UserRole.PQL.value, UserRole.BGD.value)
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if current_user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unauthorized"
                )
            
            if current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role không được phép: {current_user.role}"
                )
            
            return await func(*args, current_user=current_user, **kwargs)
        
        return wrapper
    return decorator
