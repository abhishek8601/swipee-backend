from enum import Enum
from typing import List

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MERCHANT = "merchant"
    MERCHANT_STAFF = "merchant_staff"

    @property
    def label(self) -> str:
        labels = {
            self.SUPER_ADMIN: "Super Admin",
            self.ADMIN: "Admin",
            self.MERCHANT: "Merchant",
            self.MERCHANT_STAFF: "Merchant Staff",
        }
        return labels.get(self, self.value)

    @property
    def is_merchant_side(self) -> bool:
        return self in (self.MERCHANT, self.MERCHANT_STAFF)

    @property
    def is_platform_side(self) -> bool:
        return self in (self.SUPER_ADMIN, self.ADMIN)


class MerchantStatus(str, Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"

    @property
    def label(self) -> str:
        labels = {
            self.PENDING: "Pending KYC",
            self.UNDER_REVIEW: "Under Review",
            self.APPROVED: "Approved",
            self.REJECTED: "Rejected",
            self.SUSPENDED: "Suspended",
        }
        return labels.get(self, self.value)

    @property
    def can_trade(self) -> bool:
        return self == self.APPROVED

    def allowed_transitions(self) -> List["MerchantStatus"]:
        transitions = {
            self.PENDING: [self.UNDER_REVIEW, self.APPROVED, self.REJECTED],
            self.UNDER_REVIEW: [self.APPROVED, self.REJECTED, self.PENDING],
            self.APPROVED: [self.SUSPENDED],
            self.REJECTED: [self.PENDING, self.UNDER_REVIEW],
            self.SUSPENDED: [self.APPROVED, self.REJECTED],
        }
        return transitions.get(self, [])

    def can_transition_to(self, target: "MerchantStatus") -> bool:
        return target in self.allowed_transitions()


class ProductStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"

    @property
    def label(self) -> str:
        labels = {
            self.DRAFT: "Draft",
            self.PENDING_REVIEW: "Pending Review",
            self.APPROVED: "Approved",
            self.REJECTED: "Rejected",
            self.ARCHIVED: "Archived",
        }
        return labels.get(self, self.value)

    def allowed_transitions(self) -> List["ProductStatus"]:
        transitions = {
            self.DRAFT: [self.PENDING_REVIEW, self.ARCHIVED],
            self.PENDING_REVIEW: [self.APPROVED, self.REJECTED, self.DRAFT],
            self.APPROVED: [self.ARCHIVED, self.PENDING_REVIEW],
            self.REJECTED: [self.DRAFT, self.PENDING_REVIEW, self.ARCHIVED],
            self.ARCHIVED: [self.DRAFT],
        }
        return transitions.get(self, [])

    def can_transition_to(self, target: "ProductStatus") -> bool:
        return target in self.allowed_transitions()

    @property
    def requires_admin(self) -> bool:
        return self in (self.APPROVED, self.REJECTED)

    @property
    def is_publicly_visible(self) -> bool:
        return self == self.APPROVED

    @property
    def is_editable_by_merchant(self) -> bool:
        return self in (self.DRAFT, self.REJECTED)


class MovementType(str, Enum):
    INITIAL = "initial"
    RESTOCK = "restock"
    SALE = "sale"
    UNRESERVE = "unreserve"
    SHIP = "ship"
    RETURN = "return"
    RTO = "rto"
    ADJUSTMENT = "adjustment"
    DAMAGE = "damage"
    LOST = "lost"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"

    @property
    def label(self) -> str:
        labels = {
            self.INITIAL: "Opening stock",
            self.RESTOCK: "Restock",
            self.SALE: "Reserved for order",
            self.UNRESERVE: "Reservation released",
            self.SHIP: "Shipped",
            self.RETURN: "Customer return",
            self.RTO: "Return to origin",
            self.ADJUSTMENT: "Manual adjustment",
            self.DAMAGE: "Damaged",
            self.LOST: "Lost",
            self.TRANSFER_IN: "Transfer in",
            self.TRANSFER_OUT: "Transfer out",
        }
        return labels.get(self, self.value)

    @property
    def affects(self) -> str:
        if self in (self.SALE, self.UNRESERVE):
            return "reserved"
        return "on_hand"

    @property
    def direction(self) -> int:
        if self in (self.INITIAL, self.RESTOCK, self.RETURN, self.RTO, self.TRANSFER_IN, self.SALE):
            return 1
        if self in (self.SHIP, self.DAMAGE, self.LOST, self.TRANSFER_OUT, self.UNRESERVE):
            return -1
        return 0

    @property
    def is_manual(self) -> bool:
        return self in (
            self.RESTOCK, self.ADJUSTMENT, self.DAMAGE, self.LOST,
            self.TRANSFER_IN, self.TRANSFER_OUT
        )
