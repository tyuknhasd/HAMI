from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import (
    verify_admin_credentials,
    create_access_token,
    get_current_admin,
    get_or_create_admin,
    hash_password,
)
from ..database import get_db
from ..models import Admin
from ..schemas import (
    LoginRequest, TokenResponse, ChangePasswordRequest, ChangeUsernameRequest,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    if not verify_admin_credentials(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = create_access_token(subject=payload.username)
    return TokenResponse(access_token=token)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, db: Session = Depends(get_db),
                    admin: str = Depends(get_current_admin)):
    """Lets the logged-in admin change their own password from the panel.
    No Railway env vars needed."""
    if not verify_admin_credentials(admin, payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 4 characters")
    a = get_or_create_admin(db)
    a.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True, "message": "Password changed"}


@router.post("/change-username")
def change_username(payload: ChangeUsernameRequest, db: Session = Depends(get_db),
                    admin: str = Depends(get_current_admin)):
    """Let the admin change their login username from the panel.
    Current password required for verification."""
    if not verify_admin_credentials(admin, payload.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    new_username = (payload.new_username or "").strip()
    if len(new_username) < 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New username must be at least 3 characters")
    existing = db.query(Admin).filter(Admin.username == new_username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")
    a = get_or_create_admin(db)
    a.username = new_username
    db.commit()
    # Issue a fresh token with the new subject so the session isn't broken
    return {"ok": True, "message": "Username changed", "access_token": create_access_token(subject=new_username)}


@router.get("/me")
def whoami(admin: str = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Return the current admin username (for the settings page)."""
    a = get_or_create_admin(db)
    return {"username": a.username}