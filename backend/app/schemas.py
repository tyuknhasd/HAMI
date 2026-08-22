from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from .models import Protocol


class LinkCreate(BaseModel):
    label: str = ""
    protocol: Protocol
    traffic_limit_gb: float = 0     # 0 = unlimited
    expires_in_days: Optional[int] = None  # None = never
    anti_filter: bool = False
    high_speed: bool = False
    # pass the sub_id of an existing link to add this one to the same
    # subscription group; omit it to start a new group of its own.
    sub_id: Optional[str] = None


class LinkUpdate(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None
    traffic_limit_gb: Optional[float] = None
    expires_in_days: Optional[int] = None
    anti_filter: Optional[bool] = None
    high_speed: Optional[bool] = None


class LinkOut(BaseModel):
    id: int
    uuid: str
    label: str
    protocol: Protocol
    client_id: str
    traffic_limit_bytes: int
    traffic_used_bytes: int
    expires_at: Optional[datetime]
    is_active: bool
    created_at: datetime
    connect_url: str
    qr_png_base64: Optional[str] = None
    anti_filter: bool = False
    high_speed: bool = False
    sub_id: str
    sub_url: str
    fragment_json: Optional[str] = None
    mux_json: Optional[str] = None

    class Config:
        from_attributes = True


class MTProtoCreate(BaseModel):
    label: str = ""


class MTProtoOut(BaseModel):
    id: int
    label: str
    secret: str
    is_active: bool
    connect_url: str

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangeUsernameRequest(BaseModel):
    current_password: str
    new_username: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OverviewStats(BaseModel):
    total_links: int
    active_links: int
    total_traffic_used_gb: float
    total_traffic_today_gb: float
