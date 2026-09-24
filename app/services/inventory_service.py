from datetime import datetime
from typing import Optional, Any
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.inventory import Inventory, InventoryMovement, Warehouse
from app.models.product import ProductVariant
from app.models.user import User
from app.core.enums import MovementType

class InsufficientStockException(HTTPException):
    def __init__(self, detail: str = "Insufficient available stock."):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

class InventoryService:
    @staticmethod
    def initialise(
        db: Session,
        variant: ProductVariant,
        warehouse: Warehouse,
        quantity: int = 0,
        actor: Optional[User] = None
    ) -> Inventory:
        inv = db.query(Inventory).filter(
            Inventory.product_variant_id == variant.id,
            Inventory.warehouse_id == warehouse.id
        ).first()

        if not inv:
            inv = Inventory(
                product_variant_id=variant.id,
                warehouse_id=warehouse.id,
                on_hand=0,
                reserved=0,
                low_stock_threshold=5,
                safety_stock=0
            )
            db.add(inv)
            db.flush()

        if quantity > 0:
            InventoryService.increase(
                db=db,
                inventory=inv,
                quantity=quantity,
                type_=MovementType.INITIAL,
                actor=actor,
                reason="Opening stock"
            )

        db.commit()
        db.refresh(inv)
        return inv

    @staticmethod
    def increase(
        db: Session,
        inventory: Inventory,
        quantity: int,
        type_: MovementType = MovementType.RESTOCK,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None
    ) -> Inventory:
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be positive.")

        inventory.on_hand += quantity
        inventory.last_movement_at = datetime.utcnow()

        movement = InventoryMovement(
            inventory_id=inventory.id,
            product_variant_id=inventory.product_variant_id,
            warehouse_id=inventory.warehouse_id,
            merchant_id=inventory.warehouse.merchant_id,
            type=type_.value,
            affects="on_hand",
            quantity_change=quantity,
            on_hand_after=inventory.on_hand,
            reserved_after=inventory.reserved,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason or type_.label,
            actor_id=actor.id if actor else None,
            created_at=datetime.utcnow()
        )
        db.add(movement)
        db.flush()
        return inventory

    @staticmethod
    def decrease(
        db: Session,
        inventory: Inventory,
        quantity: int,
        type_: MovementType = MovementType.DAMAGE,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None
    ) -> Inventory:
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be positive.")

        if inventory.on_hand - quantity < inventory.reserved:
            raise InsufficientStockException(
                f"Cannot reduce on_hand below reserved ({inventory.reserved} reserved, requested -{quantity} from {inventory.on_hand} on hand)."
            )

        inventory.on_hand -= quantity
        inventory.last_movement_at = datetime.utcnow()

        movement = InventoryMovement(
            inventory_id=inventory.id,
            product_variant_id=inventory.product_variant_id,
            warehouse_id=inventory.warehouse_id,
            merchant_id=inventory.warehouse.merchant_id,
            type=type_.value,
            affects="on_hand",
            quantity_change=-quantity,
            on_hand_after=inventory.on_hand,
            reserved_after=inventory.reserved,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason or type_.label,
            actor_id=actor.id if actor else None,
            created_at=datetime.utcnow()
        )
        db.add(movement)
        db.flush()
        return inventory

    @staticmethod
    def reserve(
        db: Session,
        inventory: Inventory,
        quantity: int,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None
    ) -> Inventory:
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be positive.")

        available = inventory.on_hand - inventory.reserved
        if available < quantity:
            raise InsufficientStockException(
                f"Only {available} units available; {quantity} requested."
            )

        inventory.reserved += quantity
        inventory.last_movement_at = datetime.utcnow()

        movement = InventoryMovement(
            inventory_id=inventory.id,
            product_variant_id=inventory.product_variant_id,
            warehouse_id=inventory.warehouse_id,
            merchant_id=inventory.warehouse.merchant_id,
            type=MovementType.SALE.value,
            affects="reserved",
            quantity_change=quantity,
            on_hand_after=inventory.on_hand,
            reserved_after=inventory.reserved,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason or "Reserved for order",
            actor_id=actor.id if actor else None,
            created_at=datetime.utcnow()
        )
        db.add(movement)
        db.flush()
        return inventory

    @staticmethod
    def unreserve(
        db: Session,
        inventory: Inventory,
        quantity: int,
        actor: Optional[User] = None,
        reason: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None
    ) -> Inventory:
        if quantity <= 0:
            raise HTTPException(status_code=422, detail="Quantity must be positive.")

        if inventory.reserved < quantity:
            quantity = inventory.reserved

        inventory.reserved -= quantity
        inventory.last_movement_at = datetime.utcnow()

        movement = InventoryMovement(
            inventory_id=inventory.id,
            product_variant_id=inventory.product_variant_id,
            warehouse_id=inventory.warehouse_id,
            merchant_id=inventory.warehouse.merchant_id,
            type=MovementType.UNRESERVE.value,
            affects="reserved",
            quantity_change=-quantity,
            on_hand_after=inventory.on_hand,
            reserved_after=inventory.reserved,
            reference_type=reference_type,
            reference_id=reference_id,
            reason=reason or "Reservation released",
            actor_id=actor.id if actor else None,
            created_at=datetime.utcnow()
        )
        db.add(movement)
        db.flush()
        return inventory

    @staticmethod
    def adjust(
        db: Session,
        inventory: Inventory,
        new_on_hand: int,
        actor: Optional[User] = None,
        reason: Optional[str] = None
    ) -> Inventory:
        if new_on_hand < 0:
            raise HTTPException(status_code=422, detail="Stock cannot be negative.")

        diff = new_on_hand - inventory.on_hand
        if diff == 0:
            return inventory

        if new_on_hand < inventory.reserved:
            raise InsufficientStockException(
                f"Cannot adjust stock to {new_on_hand} because {inventory.reserved} units are reserved for orders."
            )

        inventory.on_hand = new_on_hand
        inventory.last_counted_at = datetime.utcnow()
        inventory.last_movement_at = datetime.utcnow()

        movement = InventoryMovement(
            inventory_id=inventory.id,
            product_variant_id=inventory.product_variant_id,
            warehouse_id=inventory.warehouse_id,
            merchant_id=inventory.warehouse.merchant_id,
            type=MovementType.ADJUSTMENT.value,
            affects="on_hand",
            quantity_change=diff,
            on_hand_after=inventory.on_hand,
            reserved_after=inventory.reserved,
            reason=reason or "Manual stock count adjustment",
            actor_id=actor.id if actor else None,
            created_at=datetime.utcnow()
        )
        db.add(movement)
        db.flush()
        return inventory
