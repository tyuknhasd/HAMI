from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import Admin

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    # bcrypt only accepts up to 72 bytes; truncate to avoid crashes
    return pwd_context.hash(password[:72])


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain[:72], hashed)


def get_or_create_admin(db: Session) -> Admin:
    """Returns the admin account, creating it with defaults on first boot.
    Default: admin / 123456 (change it from the panel!)."""
    admin = db.query(Admin).first()
    if admin:
        return admin
    admin = Admin(
        username=settings.ADMIN_USERNAME or "admin",
        password_hash=hash_password(settings.ADMIN_PASSWORD or "123456"),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def verify_admin_credentials(username: str, password: str) -> bool:
    db = SessionLocal()
    try:
        admin = get_or_create_admin(db)
        return username == admin.username and verify_password(password, admin.password_hash)
    finally:
        db.close()


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def get_current_admin(token: str = Depends(oauth2_scheme)) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception