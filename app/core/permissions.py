from typing import List, Dict
from app.core.enums import UserRole

class Permissions:
    # --- Merchants ---
    MERCHANT_VIEW_ANY = "merchant.view_any"
    MERCHANT_VIEW = "merchant.view"
    MERCHANT_CREATE = "merchant.create"
    MERCHANT_UPDATE = "merchant.update"
    MERCHANT_APPROVE = "merchant.approve"
    MERCHANT_SUSPEND = "merchant.suspend"
    MERCHANT_DELETE = "merchant.delete"

    # --- Users / staff ---
    USER_VIEW_ANY = "user.view_any"
    USER_CREATE = "user.create"
    USER_UPDATE = "user.update"
    USER_DELETE = "user.delete"
    ADMIN_MANAGE = "admin.manage"

    # --- Catalog taxonomy ---
    CATEGORY_MANAGE = "category.manage"
    BRAND_VIEW = "brand.view"
    BRAND_MANAGE = "brand.manage"
    BRAND_APPROVE = "brand.approve"
    BRAND_PROPOSE = "brand.propose"
    ATTRIBUTE_MANAGE = "attribute.manage"
    SIZE_CHART_MANAGE = "size_chart.manage"

    # --- Products ---
    PRODUCT_VIEW_ANY = "product.view_any"
    PRODUCT_VIEW_OWN = "product.view_own"
    PRODUCT_CREATE = "product.create"
    PRODUCT_UPDATE = "product.update"
    PRODUCT_DELETE = "product.delete"
    PRODUCT_SUBMIT = "product.submit"
    PRODUCT_APPROVE = "product.approve"
    PRODUCT_TAKEDOWN = "product.takedown"
    PRODUCT_IMPORT = "product.import"

    # --- Inventory ---
    INVENTORY_VIEW = "inventory.view"
    INVENTORY_UPDATE = "inventory.update"
    INVENTORY_ADJUST = "inventory.adjust"
    WAREHOUSE_MANAGE = "warehouse.manage"

    # --- Orders ---
    ORDER_VIEW_ANY = "order.view_any"
    ORDER_VIEW_OWN = "order.view_own"
    ORDER_FULFIL = "order.fulfil"
    ORDER_CANCEL = "order.cancel"

    # --- Returns ---
    RETURN_VIEW = "return.view"
    RETURN_PROCESS = "return.process"
    RETURN_REFUND = "return.refund"

    # --- Finance ---
    COMMISSION_MANAGE = "commission.manage"
    PAYOUT_VIEW_ANY = "payout.view_any"
    PAYOUT_VIEW_OWN = "payout.view_own"
    PAYOUT_GENERATE = "payout.generate"
    PAYOUT_APPROVE = "payout.approve"
    LEDGER_ADJUST = "ledger.adjust"

    # --- AI models / virtual try-on ---
    AI_MODEL_VIEW = "ai_model.view"
    AI_MODEL_MANAGE = "ai_model.manage"
    TRY_ON_GENERATE = "try_on.generate"
    TRY_ON_PUBLISH = "try_on.publish"

    # --- Platform ---
    SETTINGS_MANAGE = "settings.manage"
    AUDIT_VIEW = "audit.view"
    REPORT_VIEW = "report.view"

    @classmethod
    def all(cls) -> List[str]:
        return [
            getattr(cls, attr) for attr in dir(cls)
            if not attr.startswith("_") and isinstance(getattr(cls, attr), str) and not callable(getattr(cls, attr))
        ]

    @classmethod
    def matrix(cls) -> Dict[str, List[str]]:
        return {
            UserRole.ADMIN.value: [
                cls.MERCHANT_VIEW_ANY, cls.MERCHANT_VIEW, cls.MERCHANT_CREATE,
                cls.MERCHANT_UPDATE, cls.MERCHANT_APPROVE, cls.MERCHANT_SUSPEND,

                cls.USER_VIEW_ANY,

                cls.CATEGORY_MANAGE,
                cls.BRAND_VIEW, cls.BRAND_MANAGE, cls.BRAND_APPROVE,
                cls.ATTRIBUTE_MANAGE, cls.SIZE_CHART_MANAGE,

                cls.PRODUCT_VIEW_ANY, cls.PRODUCT_APPROVE, cls.PRODUCT_TAKEDOWN,

                cls.AI_MODEL_VIEW, cls.AI_MODEL_MANAGE, cls.TRY_ON_PUBLISH,

                cls.INVENTORY_VIEW,

                cls.ORDER_VIEW_ANY, cls.ORDER_CANCEL,

                cls.RETURN_VIEW, cls.RETURN_PROCESS,

                cls.PAYOUT_VIEW_ANY,

                cls.AUDIT_VIEW, cls.REPORT_VIEW,
            ],

            UserRole.MERCHANT.value: [
                cls.BRAND_VIEW, cls.BRAND_PROPOSE,

                cls.PRODUCT_VIEW_OWN, cls.PRODUCT_CREATE, cls.PRODUCT_UPDATE,
                cls.PRODUCT_DELETE, cls.PRODUCT_SUBMIT, cls.PRODUCT_IMPORT,

                cls.AI_MODEL_VIEW, cls.TRY_ON_GENERATE,

                cls.INVENTORY_VIEW, cls.INVENTORY_UPDATE, cls.INVENTORY_ADJUST,
                cls.WAREHOUSE_MANAGE,

                cls.ORDER_VIEW_OWN, cls.ORDER_FULFIL, cls.ORDER_CANCEL,

                cls.RETURN_VIEW, cls.RETURN_PROCESS,

                cls.PAYOUT_VIEW_OWN,

                cls.USER_CREATE, cls.USER_UPDATE, cls.USER_DELETE, cls.USER_VIEW_ANY,

                cls.SIZE_CHART_MANAGE,
                cls.REPORT_VIEW,
            ],

            UserRole.MERCHANT_STAFF.value: [
                cls.BRAND_VIEW,

                cls.PRODUCT_VIEW_OWN, cls.PRODUCT_CREATE, cls.PRODUCT_UPDATE,
                cls.PRODUCT_SUBMIT,

                cls.AI_MODEL_VIEW,

                cls.INVENTORY_VIEW, cls.INVENTORY_UPDATE,

                cls.ORDER_VIEW_OWN, cls.ORDER_FULFIL,

                cls.RETURN_VIEW,
            ],
        }
