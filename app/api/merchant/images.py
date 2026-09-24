import os
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_merchant_can_trade
from app.models.user import User
from app.models.product import Product, ProductImage

router = APIRouter(prefix="/merchant", tags=["merchant-images"])

class ReorderSchema(BaseModel):
    order: List[int]

@router.post("/products/{product_id}/images")
async def upload_product_image(
    product_id: int,
    image: UploadFile = File(...),
    colour_attribute_value_id: Optional[int] = Form(None),
    is_primary: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.merchant_id == current_user.merchant_id,
        Product.deleted_at.is_(None)
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")

    dest_dir = settings.STORAGE_DIR / "products" / str(product.id)
    os.makedirs(dest_dir, exist_ok=True)

    ext = os.path.splitext(image.filename)[1] or ".jpg"
    filename = f"{int(time.time())}_{image.filename}"
    file_path = dest_dir / filename

    content = await image.read()
    with open(file_path, "wb") as f:
        f.write(content)

    rel_path = f"products/{product.id}/{filename}"

    # If first image or marked primary, clear existing primary
    if is_primary or len(product.images) == 0:
        db.query(ProductImage).filter(ProductImage.product_id == product.id).update({"is_primary": False})
        is_primary = True

    sort_order = len(product.images)

    img = ProductImage(
        product_id=product.id,
        colour_attribute_value_id=colour_attribute_value_id,
        image_path=rel_path,
        thumb_path=rel_path,
        is_primary=is_primary,
        sort_order=sort_order
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    return {
        "data": {
            "id": img.id,
            "image_url": f"/storage/{img.image_path}",
            "thumb_url": f"/storage/{img.thumb_path}",
            "colour_attribute_value_id": img.colour_attribute_value_id,
            "is_primary": bool(img.is_primary),
            "sort_order": img.sort_order,
        }
    }

@router.post("/products/{product_id}/images/reorder")
def reorder_images(
    product_id: int,
    data: ReorderSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    for idx, img_id in enumerate(data.order):
        db.query(ProductImage).filter(
            ProductImage.id == img_id,
            ProductImage.product_id == product_id
        ).update({"sort_order": idx})
    db.commit()
    return {"message": "Images reordered."}

@router.post("/images/{image_id}/primary")
def make_primary(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    img = db.query(ProductImage).join(Product).filter(
        ProductImage.id == image_id,
        Product.merchant_id == current_user.merchant_id
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found.")

    db.query(ProductImage).filter(ProductImage.product_id == img.product_id).update({"is_primary": False})
    img.is_primary = True
    db.commit()
    return {"message": "Primary image updated."}

@router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_merchant_can_trade)
):
    img = db.query(ProductImage).join(Product).filter(
        ProductImage.id == image_id,
        Product.merchant_id == current_user.merchant_id
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="Image not found.")

    db.delete(img)
    db.commit()
    return {"message": "Image deleted."}
