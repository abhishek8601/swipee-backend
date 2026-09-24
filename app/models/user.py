from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.enums import UserRole
from app.core.permissions import Permissions

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    avatar_path = Column(String(255), nullable=True)
    
    role = Column(String(50), default=UserRole.MERCHANT.value, nullable=False)
    merchant_id = Column(Integer, ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True, index=True)
    is_merchant_owner = Column(Boolean, default=False)
    
    status = Column(String(50), default="active", nullable=False)
    must_change_password = Column(Boolean, default=False)
    
    email_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    merchant = relationship("Merchant", back_populates="users", foreign_keys=[merchant_id])

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN.value

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    @property
    def is_merchant(self) -> bool:
        return self.role == UserRole.MERCHANT.value

    @property
    def is_merchant_staff(self) -> bool:
        return self.role == UserRole.MERCHANT_STAFF.value

    @property
    def is_merchant_side(self) -> bool:
        return self.role in (UserRole.MERCHANT.value, UserRole.MERCHANT_STAFF.value)

    @property
    def is_platform_side(self) -> bool:
        return self.role in (UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value)

    def is_active(self) -> bool:
        return self.status == "active" and self.deleted_at is None

    def get_role_enum(self) -> Optional[UserRole]:
        try:
            return UserRole(self.role)
        except ValueError:
            return None

    def get_role_label(self) -> str:
        r = self.get_role_enum()
        return r.label if r else self.role

    def get_all_permissions(self) -> List[str]:
        if self.is_super_admin:
            return Permissions.all()
        matrix = Permissions.matrix()
        return matrix.get(self.role, [])

    def has_permission(self, permission: str) -> bool:
        if self.is_super_admin:
            return True
        return permission in self.get_all_permissions()
