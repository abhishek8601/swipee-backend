from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, model_validator

class LoginRequest(BaseModel):
    email: str
    password: str
    device_name: Optional[str] = "web"


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(min_length=8, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=20)
    device_name: Optional[str] = "web"

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError("Password confirmation does not match.")
        return self


class MerchantSnippet(BaseModel):
    id: int
    display_name: str
    slug: str
    status: str
    status_label: str
    can_trade: bool
    logo_url: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    role: Optional[str] = None
    role_label: Optional[str] = None
    status: str
    merchant_id: Optional[int] = None
    is_merchant_owner: bool = False
    must_change_password: bool = False
    last_login_at: Optional[str] = None
    merchant: Optional[MerchantSnippet] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    token: str
    user: UserResponse
    must_change_password: bool = False


class MeResponse(BaseModel):
    user: UserResponse
    permissions: List[str]
    role: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    password: str
    password_confirmation: str
