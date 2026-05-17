from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User, UserRole, BGDManagement
from schemas import UserCreate, UserUpdate, UserResponse, UserListResponse
from auth import hash_password, get_current_user
from config import DEFAULT_PASSWORD

router = APIRouter(prefix="/api/admin", tags=["admin"])

def check_admin(current_user: User = Depends(get_current_user)):
    """Check if current user is admin"""
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access this endpoint"
        )
    return current_user

@router.get("/users", response_model=list[UserListResponse])
def list_users(
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db),
    skip: int = 0,
    limit: int = 100,
    role: str = None,
    department: str = None
):
    """List all users (admin only)"""
    query = db.query(User)
    
    if role:
        query = query.filter(User.role == role)
    
    if department:
        query = query.filter(User.department == department)
    
    users = query.offset(skip).limit(limit).all()
    return users

@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Get user details (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user

@router.post("/users", response_model=UserResponse)
def create_user(
    request: UserCreate,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Create new user (admin only)"""
    # Check if username exists
    existing_user = db.query(User).filter(User.username == request.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Check if email exists
    existing_email = db.query(User).filter(User.email == request.email).first()
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )
    
    # Create new user
    new_user = User(
        username=request.username,
        email=request.email,
        full_name=request.full_name,
        hashed_password=hash_password(DEFAULT_PASSWORD),
        role=request.role,
        department=request.department,
        is_active=request.is_active
    )
    
    db.add(new_user)
    db.flush()
    
    # If role is PNV/PQL and BGD manager is specified, create BGD management relationship
    if request.bgd_manager_id and request.role in [UserRole.PNV.value, UserRole.PQL.value]:
        bgd_mgmt = BGDManagement(
            bgd_id=request.bgd_manager_id,
            pnv_user_id=new_user.id
        )
        db.add(bgd_mgmt)
    
    db.commit()
    db.refresh(new_user)
    return new_user

@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    request: UserUpdate,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Update user (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Update fields
    if request.full_name:
        user.full_name = request.full_name
    if request.department:
        user.department = request.department
    if request.is_active is not None:
        user.is_active = request.is_active
    if request.role:
        user.role = request.role
    
    # Update BGD management if specified
    if request.bgd_manager_id:
        # Remove existing BGD management
        db.query(BGDManagement).filter(BGDManagement.pnv_user_id == user_id).delete()
        
        # Create new BGD management
        bgd_mgmt = BGDManagement(
            bgd_id=request.bgd_manager_id,
            pnv_user_id=user_id
        )
        db.add(bgd_mgmt)
    
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Delete user (admin only)"""
    # Prevent deleting admin
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    if user.role == UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete admin user"
        )
    
    # Delete BGD management relationship
    db.query(BGDManagement).filter(BGDManagement.pnv_user_id == user_id).delete()
    
    # Delete user
    db.delete(user)
    db.commit()
    return {"message": f"User {user_id} deleted successfully"}

@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Reset user password to default (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Reset to default password
    user.hashed_password = hash_password(DEFAULT_PASSWORD)
    db.commit()
    return {"message": f"Password for user {user.username} reset to {DEFAULT_PASSWORD}"}

@router.post("/users/{user_id}/toggle-active")
def toggle_user_active(
    user_id: int,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Toggle user active status (admin only)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    # Prevent disabling admin
    if user.role == UserRole.ADMIN.value and user.id != admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot disable admin user"
        )
    
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    return {
        "user_id": user.id,
        "username": user.username,
        "is_active": user.is_active
    }

@router.get("/users/{user_id}/bgd-management")
def get_user_bgd_management(
    user_id: int,
    admin: User = Depends(check_admin),
    db: Session = Depends(get_db)
):
    """Get BGD management relationships for a user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    if user.role == UserRole.BGD.value:
        # Get PNV users managed by this BGD
        managements = db.query(BGDManagement).filter(BGDManagement.bgd_id == user_id).all()
        return {
            "bgd_user_id": user_id,
            "bgd_user_name": user.full_name,
            "managed_pnv_users": [
                {
                    "id": m.pnv_user_id,
                    "username": db.query(User).filter(User.id == m.pnv_user_id).first().username
                }
                for m in managements
            ]
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a BGD user"
        )
