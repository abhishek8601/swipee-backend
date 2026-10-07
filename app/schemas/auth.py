import re
from typing import Literal, Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator, model_validator

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


class BuyerRegisterRequest(BaseModel):
    """Payload accepted for a public buyer/customer account registration."""

    name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(min_length=8, max_length=128)
    gender: Optional[Literal["male", "female", "prefer_not_to_say"]] = None
    terms_accepted: bool

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name must not be blank.")
        return value

    @field_validator("phone")
    @classmethod
    def phone_must_be_valid(cls, value: str) -> str:
        normalized = value.replace(" ", "").replace("-", "")
        if not re.fullmatch(r"\+?[1-9]\d{6,14}", normalized):
            raise ValueError("Phone must be a valid phone number.")
        return normalized

    @field_validator("password_confirmation")
    @classmethod
    def passwords_must_match(cls, value: str, info: ValidationInfo) -> str:
        if "password" in info.data and value != info.data["password"]:
            raise ValueError("Password confirmation does not match.")
        return value

    @field_validator("terms_accepted")
    @classmethod
    def terms_must_be_accepted(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Terms must be accepted.")
        return value

    @property
    def normalized_phone(self) -> str:
        return self.phone


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


class BuyerUserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str
    gender: Optional[str] = None
    role: str


class BuyerRegisterResponse(BaseModel):
    success: bool = True
    message: str
    user: BuyerUserResponse
    token: str


class MeResponse(BaseModel):
    user: UserResponse
    permissions: List[str]
    role: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    password: str
    password_confirmation: str
