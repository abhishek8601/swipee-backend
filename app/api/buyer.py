from datetime import datetime
from typing import Dict, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.enums import MerchantStatus, ProductStatus, UserRole
from app.models.buyer import BodyProfile, Cart, CartItem, UserAddress, WishlistItem
from app.models.inventory import Inventory
from app.models.order import Customer, Order, OrderItem
from app.models.product import Product, ProductVariant
from app.models.taxonomy import Category
from app.models.user import User

router = APIRouter(tags=["buyer"])

def buyer(user: User = Depends(get_current_user)):
    if user.role not in (UserRole.BUYER.value, UserRole.CUSTOMER.value): raise HTTPException(403, "Buyer access required.")
    return user

class ProfileInput(BaseModel):
    name: str = Field(min_length=2, max_length=255); phone: str = Field(min_length=7, max_length=20); gender: Optional[str] = None
class BodyInput(BaseModel):
    measurements: Dict[str, float]; source: str = "manual"; is_confirmed: bool = False
class CartInput(BaseModel):
    product_id: int; variant_id: int; quantity: int = Field(ge=1, le=20)
class QuantityInput(BaseModel): quantity: int = Field(ge=1, le=20)
class AddressInput(BaseModel):
    full_name: str; phone: str; address_line1: str; address_line2: Optional[str] = None; city: str; state: str; postal_code: str; country: str = "India"; is_default: bool = False
class CheckoutInput(BaseModel):
    address_id: int
    payment_method: Literal["cod", "razorpay_dummy"] = "cod"

def product_visible(product: Product): return product and product.deleted_at is None and product.is_active and product.status == ProductStatus.APPROVED.value and product.merchant and product.merchant.status == MerchantStatus.APPROVED.value
def cart_for(db, user):
    cart = db.query(Cart).filter(Cart.user_id == user.id).first()
    if not cart: cart = Cart(user_id=user.id); db.add(cart); db.flush()
    return cart
def cart_data(cart):
    return [{"id": i.id, "product_id": i.product_id, "variant_id": i.variant_id, "name": i.product.name, "quantity": i.quantity, "unit_price": float(i.variant.effective_selling_price), "total": float(i.variant.effective_selling_price) * i.quantity} for i in cart.items]

@router.get("/profile")
def get_profile(user: User = Depends(buyer)): return {"success": True, "message": "Profile fetched successfully.", "data": {"id": user.id, "name": user.name, "email": user.email, "phone": user.phone, "gender": user.gender, "photo_url": f"/storage/{user.avatar_path}" if user.avatar_path else None}}
@router.put("/profile")
def update_profile(data: ProfileInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    user.name, user.phone, user.gender = data.name.strip(), data.phone.strip(), data.gender; db.commit(); return get_profile(user)
@router.get("/body-profile")
def get_body(db: Session = Depends(get_db), user: User = Depends(buyer)):
    row = db.query(BodyProfile).filter_by(user_id=user.id).first()
    if not row: raise HTTPException(404, "Body profile not found.")
    return {"success": True, "message": "Body profile fetched successfully.", "data": {"measurements": row.measurements, "source": row.source, "camera_status": row.camera_status, "is_confirmed": row.is_confirmed}}
@router.post("/body-profile")
@router.put("/body-profile")
def save_body(data: BodyInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    row = db.query(BodyProfile).filter_by(user_id=user.id).first() or BodyProfile(user_id=user.id)
    row.measurements, row.source, row.is_confirmed = data.measurements, data.source, data.is_confirmed; db.add(row); db.commit(); return {"success": True, "message": "Body profile saved successfully.", "data": {"measurements": row.measurements}}
@router.delete("/body-profile")
def delete_body(db: Session = Depends(get_db), user: User = Depends(buyer)):
    db.query(BodyProfile).filter_by(user_id=user.id).delete(); db.commit(); return {"success": True, "message": "Body profile deleted successfully.", "data": {}}
@router.get("/categories")
def categories(db: Session = Depends(get_db)): return {"success": True, "message": "Categories fetched successfully.", "data": [{"id": c.id, "name": c.name, "slug": c.slug} for c in db.query(Category).filter(Category.is_active.is_(True), Category.deleted_at.is_(None)).all()]}
@router.get("/products")
@router.get("/feed")
def products(category_id: Optional[int] = None, search: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Product).filter(Product.status == ProductStatus.APPROVED.value, Product.is_active.is_(True), Product.deleted_at.is_(None))
    if category_id: q = q.filter(Product.category_id == category_id)
    if search: q = q.filter(Product.name.ilike(f"%{search}%"))
    return {"success": True, "message": "Products fetched successfully.", "data": [{"id": p.id, "name": p.name, "price": float(p.selling_price), "merchant": p.merchant.display_name, "thumbnail_url": f"/storage/{p.primary_image.image_path}" if p.primary_image else None} for p in q.all() if product_visible(p)]}
@router.get("/wishlist")
def wishlist(db: Session = Depends(get_db), user: User = Depends(buyer)): return {"success": True, "message": "Wishlist fetched successfully.", "data": [{"id": w.id, "product_id": w.product_id, "name": w.product.name} for w in db.query(WishlistItem).filter_by(user_id=user.id).all()]}
@router.post("/wishlist")
def add_wishlist(data: CartInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    product = db.query(Product).filter_by(id=data.product_id).first()
    if not product_visible(product): raise HTTPException(404, "Product not found.")
    if not db.query(WishlistItem).filter_by(user_id=user.id, product_id=product.id).first(): db.add(WishlistItem(user_id=user.id, product_id=product.id)); db.commit()
    return {"success": True, "message": "Product added to wishlist.", "data": {"product_id": product.id}}
@router.delete("/wishlist/{product_id}")
def remove_wishlist(product_id: int, db: Session = Depends(get_db), user: User = Depends(buyer)):
    db.query(WishlistItem).filter_by(user_id=user.id, product_id=product_id).delete(); db.commit(); return {"success": True, "message": "Product removed from wishlist.", "data": {}}
@router.get("/cart")
def get_cart(db: Session = Depends(get_db), user: User = Depends(buyer)):
    cart = cart_for(db, user); return {"success": True, "message": "Cart fetched successfully.", "data": {"items": cart_data(cart)}}
@router.post("/cart/items")
def add_cart(data: CartInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    product = db.query(Product).filter_by(id=data.product_id).first(); variant = db.query(ProductVariant).filter_by(id=data.variant_id, product_id=data.product_id).first()
    if not product_visible(product) or not variant: raise HTTPException(422, "Product or variant is unavailable.")
    available = sum(i.on_hand-i.reserved for i in variant.inventory)
    if data.quantity > available: raise HTTPException(422, "Insufficient stock.")
    cart = cart_for(db,user); item = db.query(CartItem).filter_by(cart_id=cart.id, variant_id=variant.id).first()
    if item: item.quantity = data.quantity
    else: db.add(CartItem(cart_id=cart.id, product_id=product.id, variant_id=variant.id, quantity=data.quantity))
    db.commit(); return get_cart(db,user)
@router.put("/cart/items/{item_id}")
def update_cart(item_id: int, data: QuantityInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    item = db.query(CartItem).join(Cart).filter(CartItem.id == item_id, Cart.user_id == user.id).first()
    if not item: raise HTTPException(404, "Cart item not found.")
    if data.quantity > sum(i.on_hand-i.reserved for i in item.variant.inventory): raise HTTPException(422, "Insufficient stock.")
    item.quantity = data.quantity; db.commit(); return get_cart(db,user)
@router.delete("/cart/items/{item_id}")
def delete_cart_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(buyer)):
    item = db.query(CartItem).join(Cart).filter(CartItem.id == item_id, Cart.user_id == user.id).first()
    if not item: raise HTTPException(404, "Cart item not found.")
    db.delete(item); db.commit(); return {"success": True, "message": "Cart item removed successfully.", "data": {}}
@router.delete("/cart")
def clear_cart(db: Session = Depends(get_db), user: User = Depends(buyer)):
    cart = cart_for(db,user); db.query(CartItem).filter_by(cart_id=cart.id).delete(); db.commit(); return {"success": True, "message": "Cart cleared successfully.", "data": {}}

def address_data(a): return {"id": a.id, "full_name": a.full_name, "phone": a.phone, "address_line1": a.address_line1, "address_line2": a.address_line2, "city": a.city, "state": a.state, "postal_code": a.postal_code, "country": a.country, "is_default": a.is_default}
@router.get("/addresses")
def addresses(db: Session = Depends(get_db), user: User = Depends(buyer)): return {"success": True, "message": "Addresses fetched successfully.", "data": [address_data(a) for a in db.query(UserAddress).filter_by(user_id=user.id).all()]}
@router.post("/addresses")
def add_address(data: AddressInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    if data.is_default: db.query(UserAddress).filter_by(user_id=user.id).update({"is_default": False})
    row = UserAddress(user_id=user.id, **data.model_dump()); db.add(row); db.commit(); db.refresh(row); return {"success": True, "message": "Address saved successfully.", "data": address_data(row)}
@router.get("/addresses/{address_id}")
def get_address(address_id: int, db: Session = Depends(get_db), user: User = Depends(buyer)):
    row = db.query(UserAddress).filter_by(id=address_id, user_id=user.id).first()
    if not row: raise HTTPException(404, "Address not found.")
    return {"success": True, "message": "Address fetched successfully.", "data": address_data(row)}
@router.put("/addresses/{address_id}")
def update_address(address_id: int, data: AddressInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    row = db.query(UserAddress).filter_by(id=address_id, user_id=user.id).first()
    if not row: raise HTTPException(404, "Address not found.")
    if data.is_default: db.query(UserAddress).filter(UserAddress.user_id == user.id, UserAddress.id != row.id).update({"is_default": False})
    for key,value in data.model_dump().items(): setattr(row,key,value)
    db.commit(); return {"success": True, "message": "Address updated successfully.", "data": address_data(row)}
@router.delete("/addresses/{address_id}")
def delete_address(address_id: int, db: Session = Depends(get_db), user: User = Depends(buyer)):
    row = db.query(UserAddress).filter_by(id=address_id, user_id=user.id).first()
    if not row: raise HTTPException(404, "Address not found.")
    db.delete(row); db.commit(); return {"success": True, "message": "Address deleted successfully.", "data": {}}

@router.post("/checkout")
def checkout(data: CheckoutInput, db: Session = Depends(get_db), user: User = Depends(buyer)):
    cart = cart_for(db,user); address = db.query(UserAddress).filter_by(id=data.address_id, user_id=user.id).first()
    if not address: raise HTTPException(422, "A valid delivery address is required.")
    if not cart.items: raise HTTPException(422, "Your cart is empty.")
    customer = db.query(Customer).filter_by(email=user.email).first()
    if not customer: customer = Customer(name=user.name, email=user.email, phone=user.phone); db.add(customer); db.flush()
    total = 0
    for item in cart.items:
        if not product_visible(item.product): raise HTTPException(422, f"{item.product.name} is unavailable.")
        available = sum(i.on_hand-i.reserved for i in item.variant.inventory)
        if item.quantity > available: raise HTTPException(422, f"Insufficient stock for {item.product.name}.")
        total += float(item.variant.effective_selling_price) * item.quantity
    order = Order(order_number=f"SW{datetime.utcnow():%Y%m%d%H%M%S}{user.id}", customer_id=customer.id, status="pending", items_subtotal=total, grand_total=total, payment_method=data.payment_method, payment_status="pending" if data.payment_method == "razorpay_dummy" else "cod_pending", shipping_name=address.full_name, shipping_phone=address.phone, shipping_address_line1=address.address_line1, shipping_address_line2=address.address_line2, shipping_city=address.city, shipping_state=address.state, shipping_postal_code=address.postal_code)
    db.add(order); db.flush()
    for item in cart.items:
        price=float(item.variant.effective_selling_price); warehouse_inventory=next((i for i in item.variant.inventory if i.on_hand-i.reserved >= item.quantity),None)
        warehouse_id=warehouse_inventory.warehouse_id if warehouse_inventory else None
        if warehouse_inventory: warehouse_inventory.reserved += item.quantity
        db.add(OrderItem(order_id=order.id, merchant_id=item.product.merchant_id, product_id=item.product_id, product_variant_id=item.variant_id, warehouse_id=warehouse_id, product_name=item.product.name, variant_sku=item.variant.sku, quantity=item.quantity, mrp=item.variant.effective_mrp, unit_price=price, total_amount=price*item.quantity))
    db.query(CartItem).filter_by(cart_id=cart.id).delete(); db.commit()
    return {"success": True, "message": "Order created successfully.", "data": {"order_id": order.id, "order_number": order.order_number, "amount": total, "payment_method": data.payment_method, "payment_status": order.payment_status}}
@router.post("/payment/create")
def create_dummy_payment(data: CheckoutInput, user: User = Depends(buyer)):
    if data.payment_method != "razorpay_dummy": raise HTTPException(422, "Only razorpay_dummy is supported by this test adapter.")
    return {"success": True, "message": "Dummy Razorpay order created.", "data": {"gateway": "razorpay_dummy", "note": "Test adapter only; use /checkout to create a server-calculated order."}}
