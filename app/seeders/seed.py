import os
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine, Base
from app.core.security import get_password_hash
from app.core.enums import UserRole, MerchantStatus, ProductStatus, MovementType
import app.models  # Ensure all models are loaded
from app.models.user import User
from app.models.merchant import Merchant, MerchantAddress, MerchantBankAccount
from app.models.taxonomy import Category, Brand, Attribute, AttributeValue
from app.models.product import Product, ProductVariant, ProductImage, ProductAttributeValue, ProductApprovalHistory
from app.models.inventory import Warehouse, Inventory, InventoryMovement
from app.models.order import Customer, Order, OrderItem
from app.models.ai_model import AiModel
from app.services.inventory_service import InventoryService

def run_seed():
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    try:
        print("Seeding Platform Staff...")
        hashed_pw = get_password_hash("password")

        superadmin = db.query(User).filter(User.email == "superadmin@swipee.test").first()
        if not superadmin:
            superadmin = User(
                name="Super Admin",
                email="superadmin@swipee.test",
                password=hashed_pw,
                role=UserRole.SUPER_ADMIN.value,
                status="active",
                email_verified_at=datetime.utcnow()
            )
            db.add(superadmin)

        admin = db.query(User).filter(User.email == "admin@swipee.test").first()
        if not admin:
            admin = User(
                name="Priya Sharma",
                email="admin@swipee.test",
                password=hashed_pw,
                role=UserRole.ADMIN.value,
                status="active",
                email_verified_at=datetime.utcnow()
            )
            db.add(admin)

        db.commit()

        print("Seeding Taxonomy (Categories)...")
        cats_data = [
            ("Men", "men", None, 0, False),
            ("Women", "women", None, 0, False),
            ("Footwear", "footwear", None, 0, False),
            ("Accessories", "accessories", None, 0, False),
            ("Topwear", "men-topwear", "men", 1, False),
            ("Bottomwear", "men-bottomwear", "men", 1, False),
            ("T-Shirts", "men-t-shirts", "men-topwear", 2, True),
            ("Shirts", "men-shirts", "men-topwear", 2, True),
            ("Jeans", "men-jeans", "men-bottomwear", 2, True),
            ("Sneakers", "sneakers", "footwear", 1, True),
            ("Watches", "watches", "accessories", 1, True),
        ]

        cat_map = {}
        for name, slug, parent_slug, level, is_leaf in cats_data:
            c = db.query(Category).filter(Category.slug == slug).first()
            if not c:
                parent_id = cat_map[parent_slug].id if parent_slug and parent_slug in cat_map else None
                path = f"{cat_map[parent_slug].path}/{slug}" if parent_slug and parent_slug in cat_map else slug
                c = Category(
                    name=name,
                    slug=slug,
                    parent_id=parent_id,
                    level=level,
                    is_leaf=is_leaf,
                    path=path,
                    commission_rate=15.00,
                    tax_rate=12.00,
                    is_active=True
                )
                db.add(c)
                db.flush()
            cat_map[slug] = c

        db.commit()

        print("Seeding Attributes...")
        # Size
        attr_size = db.query(Attribute).filter(Attribute.code == "size").first()
        if not attr_size:
            attr_size = Attribute(name="Size", code="size", type="select", is_required=True, is_variant_axis=True, is_filterable=True)
            db.add(attr_size)
            db.flush()
            sizes = [("S", "Small"), ("M", "Medium"), ("L", "Large"), ("XL", "Extra Large"), ("UK 7", "UK 7"), ("UK 8", "UK 8"), ("UK 9", "UK 9")]
            for idx, (val, lbl) in enumerate(sizes):
                db.add(AttributeValue(attribute_id=attr_size.id, value=val, label=lbl, sort_order=idx))

        # Colour
        attr_colour = db.query(Attribute).filter(Attribute.code == "colour").first()
        if not attr_colour:
            attr_colour = Attribute(name="Colour", code="colour", type="select", is_required=True, is_variant_axis=True, is_filterable=True)
            db.add(attr_colour)
            db.flush()
            colours = [
                ("navy", "Navy Blue", "#000080"),
                ("black", "Jet Black", "#000000"),
                ("white", "Optical White", "#FFFFFF"),
                ("red", "Crimson Red", "#DC143C"),
                ("olive", "Olive Green", "#556B2F")
            ]
            for idx, (val, lbl, hex_c) in enumerate(colours):
                db.add(AttributeValue(attribute_id=attr_colour.id, value=val, label=lbl, hex_color=hex_c, sort_order=idx))

        # Neck
        attr_neck = db.query(Attribute).filter(Attribute.code == "neck_type").first()
        if not attr_neck:
            attr_neck = Attribute(name="Neck Type", code="neck_type", type="select", is_required=False, is_variant_axis=False, is_filterable=True)
            db.add(attr_neck)
            db.flush()
            necks = ["Round Neck", "Polo Collar", "V-Neck"]
            for idx, n in enumerate(necks):
                db.add(AttributeValue(attribute_id=attr_neck.id, value=n.lower().replace(" ", "-"), label=n, sort_order=idx))

        # Attach attributes to T-Shirts category
        tshirt_cat = cat_map.get("men-t-shirts")
        if tshirt_cat:
            for a in [attr_size, attr_colour, attr_neck]:
                if a not in tshirt_cat.attributes:
                    tshirt_cat.attributes.append(a)

        print("Seeding Brands...")
        brands_data = ["Roadster", "HRX", "Mast & Harbour", "Puma", "Nike", "Titan"]
        brand_map = {}
        for b_name in brands_data:
            slug = b_name.lower().replace(" ", "-").replace("&", "and")
            b = db.query(Brand).filter(Brand.slug == slug).first()
            if not b:
                b = Brand(name=b_name, slug=slug, status="approved", is_active=True)
                db.add(b)
                db.flush()
            brand_map[b_name] = b

        print("Seeding AI Models...")
        models_data = [
            ("Arjun", "arjun", "male", "Athletic", "185 cm", "M", "Indian male model, fit build"),
            ("Meera", "meera", "female", "Slender", "172 cm", "S", "Indian female model, elegant look"),
            ("Kabir", "kabir", "male", "Average", "178 cm", "L", "Indian male model, casual lifestyle"),
            ("Ananya", "ananya", "female", "Petite", "165 cm", "XS", "Indian female model, vibrant modern style"),
        ]
        for name, slug, gender, body, height, size, desc in models_data:
            m = db.query(AiModel).filter(AiModel.slug == slug).first()
            if not m:
                m = AiModel(
                    name=name,
                    slug=slug,
                    gender=gender,
                    body_type=body,
                    height_cm=height,
                    reference_size=size,
                    description=desc,
                    supported_categories=["men-t-shirts", "men-shirts", "sneakers"],
                    is_active=True
                )
                db.add(m)

        db.commit()

        print("Seeding Demo Merchants...")
        # 1. Approved Merchant: Trendsetter
        trendsetter = db.query(Merchant).filter(Merchant.slug == "trendsetter").first()
        if not trendsetter:
            trendsetter = Merchant(
                legal_name="Trendsetter Apparel Pvt Ltd",
                display_name="Trendsetter",
                slug="trendsetter",
                email="owner@trendsetter.test",
                phone="9876543210",
                business_type="private_limited",
                gstin="29ABCDE1234F1Z5",
                pan="ABCDE1234F",
                status=MerchantStatus.APPROVED.value,
                default_commission_rate=14.50,
                onboarded_at=datetime.utcnow()
            )
            db.add(trendsetter)
            db.flush()

            # Merchant Owner
            db.add(User(
                name="Vikram Sethi",
                email="owner@trendsetter.test",
                password=hashed_pw,
                role=UserRole.MERCHANT.value,
                merchant_id=trendsetter.id,
                is_merchant_owner=True,
                status="active",
                email_verified_at=datetime.utcnow()
            ))

            # Merchant Staff
            db.add(User(
                name="Anil Kumar",
                email="staff@trendsetter.test",
                password=hashed_pw,
                role=UserRole.MERCHANT_STAFF.value,
                merchant_id=trendsetter.id,
                is_merchant_owner=False,
                status="active",
                email_verified_at=datetime.utcnow()
            ))

            # Warehouse
            wh = Warehouse(
                merchant_id=trendsetter.id,
                name="Mumbai Central Hub",
                code="MUM-01",
                contact_person="Vikram Sethi",
                phone="9876543210",
                address_line1="Plot 42, MIDC Andheri East",
                city="Mumbai",
                state="Maharashtra",
                postal_code="400093",
                is_primary=True,
                is_active=True
            )
            db.add(wh)
            db.flush()

            # Seed a product with variants and stock
            size_m = db.query(AttributeValue).join(Attribute).filter(Attribute.code == "size", AttributeValue.value == "M").first()
            size_l = db.query(AttributeValue).join(Attribute).filter(Attribute.code == "size", AttributeValue.value == "L").first()
            clr_navy = db.query(AttributeValue).join(Attribute).filter(Attribute.code == "colour", AttributeValue.value == "navy").first()

            prod = Product(
                merchant_id=trendsetter.id,
                category_id=tshirt_cat.id if tshirt_cat else 1,
                brand_id=brand_map["Roadster"].id if "Roadster" in brand_map else 1,
                name="Roadster Navy Slim Fit T-Shirt",
                slug="roadster-navy-slim-fit-t-shirt",
                style_code="RD-TS-001",
                mrp=999.00,
                selling_price=599.00,
                cost_price=250.00,
                short_description="Premium cotton slim fit t-shirt in navy blue.",
                description="Crafted from 100% combed cotton, this navy blue t-shirt offers exceptional comfort and durability for daily wear.",
                highlights=["100% Combed Cotton", "Slim Fit", "Bio-washed", "Pre-shrunk fabric"],
                status=ProductStatus.APPROVED.value,
                approved_at=datetime.utcnow(),
                is_active=True,
                is_featured=True
            )
            db.add(prod)
            db.flush()

            # Variants
            v1 = ProductVariant(
                product_id=prod.id,
                sku="RD-TS-001-NAV-M",
                size_attribute_value_id=size_m.id if size_m else None,
                colour_attribute_value_id=clr_navy.id if clr_navy else None,
                mrp=999.00,
                selling_price=599.00,
                is_active=True
            )
            v2 = ProductVariant(
                product_id=prod.id,
                sku="RD-TS-001-NAV-L",
                size_attribute_value_id=size_l.id if size_l else None,
                colour_attribute_value_id=clr_navy.id if clr_navy else None,
                mrp=999.00,
                selling_price=599.00,
                is_active=True
            )
            db.add_all([v1, v2])
            db.flush()

            # Stock
            InventoryService.initialise(db, v1, wh, quantity=50)
            InventoryService.initialise(db, v2, wh, quantity=35)

        # 2. Second Approved Merchant: Kicks & Co
        kicks = db.query(Merchant).filter(Merchant.slug == "kicks-and-co").first()
        if not kicks:
            kicks = Merchant(
                legal_name="Kicks & Co Retail LLP",
                display_name="Kicks & Co",
                slug="kicks-and-co",
                email="owner@kicksandco.test",
                phone="9811223344",
                business_type="llp",
                gstin="27FGHIJ5678K2Z9",
                pan="FGHIJ5678K",
                status=MerchantStatus.APPROVED.value,
                default_commission_rate=17.00,
                onboarded_at=datetime.utcnow()
            )
            db.add(kicks)
            db.flush()

            db.add(User(
                name="Rohan Mehra",
                email="owner@kicksandco.test",
                password=hashed_pw,
                role=UserRole.MERCHANT.value,
                merchant_id=kicks.id,
                is_merchant_owner=True,
                status="active",
                email_verified_at=datetime.utcnow()
            ))

        # 3. UnderReview Merchant: Nova Fashions
        nova = db.query(Merchant).filter(Merchant.slug == "nova-fashions").first()
        if not nova:
            nova = Merchant(
                legal_name="Nova Fashions",
                display_name="Nova Fashions",
                slug="nova-fashions",
                email="owner@novafashions.test",
                phone="9844556677",
                business_type="proprietorship",
                pan="KLMNO9012P",
                status=MerchantStatus.UNDER_REVIEW.value,
                default_commission_rate=15.00
            )
            db.add(nova)
            db.flush()

            db.add(User(
                name="Kavita Reddy",
                email="owner@novafashions.test",
                password=hashed_pw,
                role=UserRole.MERCHANT.value,
                merchant_id=nova.id,
                is_merchant_owner=True,
                status="active",
                email_verified_at=datetime.utcnow()
            ))

        # 4. Suspended Merchant: Halted Traders
        halted = db.query(Merchant).filter(Merchant.slug == "halted-traders").first()
        if not halted:
            halted = Merchant(
                legal_name="Halted Traders",
                display_name="Halted Traders",
                slug="halted-traders",
                email="owner@halted.test",
                phone="9899887766",
                business_type="proprietorship",
                pan="QRSTU3456V",
                status=MerchantStatus.SUSPENDED.value,
                status_reason="Repeated late dispatches. Under investigation.",
                default_commission_rate=15.00
            )
            db.add(halted)
            db.flush()

            db.add(User(
                name="Deepak Joshi",
                email="owner@halted.test",
                password=hashed_pw,
                role=UserRole.MERCHANT.value,
                merchant_id=halted.id,
                is_merchant_owner=True,
                status="active",
                email_verified_at=datetime.utcnow()
            ))

        db.commit()
        print("Database seeded successfully!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run_seed()
