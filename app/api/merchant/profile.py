from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_merchant, get_current_user
from app.core.enums import MerchantStatus
from app.models.merchant import Merchant, MerchantAddress, MerchantBankAccount, MerchantDocument
from app.models.user import User

router = APIRouter(prefix="/merchant/profile", tags=["merchant-profile"])

REQUIRED_DOCUMENTS = {"pan", "cancelled_cheque"}


class ProfileUpdate(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    display_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=20)
    business_type: Optional[Literal["proprietorship", "partnership", "llp", "private_limited", "other"]] = None
    gstin: Optional[str] = Field(default=None, max_length=15)
    pan: Optional[str] = Field(default=None, max_length=10)
    cin: Optional[str] = Field(default=None, max_length=21)
    description: Optional[str] = None
    website: Optional[str] = Field(default=None, max_length=255)


class AddressInput(BaseModel):
    type: Literal["registered", "billing", "warehouse"] = "registered"
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    postal_code: str
    country: str = "India"
    is_primary: bool = True


class DocumentInput(BaseModel):
    document_type: Literal["pan", "gst", "cancelled_cheque", "cin", "address_proof"]
    file_path: str = Field(description="Path returned by the file-upload service, e.g. merchant-documents/pan.pdf")


class BankAccountInput(BaseModel):
    account_holder_name: str
    account_number: str = Field(min_length=6, max_length=50)
    ifsc_code: str = Field(min_length=5, max_length=20)
    bank_name: str
    branch_name: Optional[str] = None
    is_primary: bool = True


def format_profile(merchant: Merchant) -> dict:
    return {
        "id": merchant.id,
        "legal_name": merchant.legal_name,
        "display_name": merchant.display_name,
        "email": merchant.email,
        "phone": merchant.phone,
        "business_type": merchant.business_type,
        "gstin": merchant.gstin,
        "pan": merchant.pan,
        "cin": merchant.cin,
        "description": merchant.description,
        "website": merchant.website,
        "verification": {
            "status": merchant.status,
            "status_label": merchant.status_label,
            "reason": merchant.status_reason,
            "can_trade": merchant.can_trade,
            "required_documents": sorted(REQUIRED_DOCUMENTS),
        },
        "addresses": [{
            "id": address.id, "type": address.type, "address_line1": address.address_line1,
            "address_line2": address.address_line2, "city": address.city, "state": address.state,
            "postal_code": address.postal_code, "country": address.country, "is_primary": bool(address.is_primary),
        } for address in merchant.addresses],
        "documents": [{
            "id": document.id, "document_type": document.document_type, "file_url": f"/storage/{document.file_path}",
            "status": document.status, "rejection_reason": document.rejection_reason,
        } for document in merchant.documents],
        "bank_accounts": [{
            "id": account.id, "account_holder_name": account.account_holder_name,
            "account_number": f"****{account.account_number[-4:]}", "ifsc_code": account.ifsc_code,
            "bank_name": account.bank_name, "branch_name": account.branch_name,
            "is_verified": bool(account.is_verified), "is_primary": bool(account.is_primary),
        } for account in merchant.bank_accounts],
    }


@router.get("")
def get_profile(merchant: Merchant = Depends(get_current_merchant)):
    return {"data": format_profile(merchant)}


@router.put("")
def update_profile(data: ProfileUpdate, db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    conflict = db.query(Merchant).filter(Merchant.email == str(data.email).lower(), Merchant.id != merchant.id).first()
    if conflict:
        raise HTTPException(status_code=422, detail="A merchant with this email already exists.")
    for field, value in data.model_dump().items():
        setattr(merchant, field, str(value).lower() if field == "email" else value)
    db.commit()
    db.refresh(merchant)
    return {"data": format_profile(merchant)}


@router.post("/addresses", status_code=status.HTTP_201_CREATED)
def save_address(data: AddressInput, db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    if data.is_primary:
        db.query(MerchantAddress).filter(MerchantAddress.merchant_id == merchant.id, MerchantAddress.type == data.type).update({"is_primary": False})
    address = MerchantAddress(merchant_id=merchant.id, **data.model_dump())
    db.add(address)
    db.commit()
    return {"message": "Business address saved.", "data": format_profile(merchant)}


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def upload_document(data: DocumentInput, db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    document = db.query(MerchantDocument).filter(MerchantDocument.merchant_id == merchant.id, MerchantDocument.document_type == data.document_type).first()
    if document:
        document.file_path, document.status, document.rejection_reason, document.verified_at = data.file_path, "pending", None, None
    else:
        document = MerchantDocument(merchant_id=merchant.id, **data.model_dump())
        db.add(document)
    db.commit()
    return {"message": "Verification document submitted.", "data": format_profile(merchant)}


@router.post("/bank-accounts", status_code=status.HTTP_201_CREATED)
def save_bank_account(data: BankAccountInput, db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    if data.is_primary:
        db.query(MerchantBankAccount).filter(MerchantBankAccount.merchant_id == merchant.id).update({"is_primary": False})
    account = MerchantBankAccount(merchant_id=merchant.id, **data.model_dump())
    db.add(account)
    db.commit()
    return {"message": "Payout details saved and pending verification.", "data": format_profile(merchant)}


@router.post("/submit-verification")
def submit_verification(db: Session = Depends(get_db), merchant: Merchant = Depends(get_current_merchant)):
    if merchant.status == MerchantStatus.APPROVED.value:
        raise HTTPException(status_code=422, detail="This seller profile is already verified.")
    if not merchant.addresses:
        raise HTTPException(status_code=422, detail="A business address is required before verification.")
    types = {document.document_type for document in merchant.documents}
    missing = REQUIRED_DOCUMENTS - types
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required documents: {', '.join(sorted(missing))}.")
    if not merchant.bank_accounts:
        raise HTTPException(status_code=422, detail="Payout details are required before verification.")
    merchant.status = MerchantStatus.UNDER_REVIEW.value
    merchant.status_reason = None
    db.commit()
    return {"message": "Seller profile submitted for verification.", "data": format_profile(merchant)}
