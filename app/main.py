import os
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.database import Base, engine
import app.models  # Register all models for Base.metadata

# API Routers
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.taxonomy import router as taxonomy_router

from app.api.merchant.products import router as merchant_products_router
from app.api.merchant.variants import router as merchant_variants_router
from app.api.merchant.images import router as merchant_images_router
from app.api.merchant.inventory import router as merchant_inventory_router
from app.api.merchant.warehouses import router as merchant_warehouses_router
from app.api.merchant.try_ons import router as merchant_tryons_router
from app.api.merchant.orders import router as merchant_orders_router

from app.api.admin.merchants import router as admin_merchants_router
from app.api.admin.products import router as admin_products_router
from app.api.admin.ai_models import router as admin_aimodels_router
from app.api.admin.categories import router as admin_categories_router
from app.api.admin.brands import router as admin_brands_router
from app.api.admin.orders import router as admin_orders_router

app = FastAPI(
    title="Swipee API",
    description="Multi-vendor Fashion Marketplace Admin API (Python/FastAPI)",
    version="1.0.0"
)

# CORS configuration
origins = [
    settings.FRONTEND_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local development flexibility
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file storage mount
os.makedirs(settings.STORAGE_DIR, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(settings.STORAGE_DIR)), name="storage")

# Create tables if not existing
Base.metadata.create_all(bind=engine)

# Laravel-compatible error formatting
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = {}
    for err in exc.errors():
        field = err["loc"][-1] if err["loc"] else "body"
        msg = err["msg"]
        if field not in errors:
            errors[str(field)] = []
        errors[str(field)].append(msg)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "message": "The given data was invalid.",
            "errors": errors
        }
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail}
    )

# Include API Routers under /api
api_prefix = "/api"

app.include_router(auth_router, prefix=api_prefix)
app.include_router(dashboard_router, prefix=api_prefix)
app.include_router(taxonomy_router, prefix=api_prefix)

# Merchant
app.include_router(merchant_products_router, prefix=api_prefix)
app.include_router(merchant_variants_router, prefix=api_prefix)
app.include_router(merchant_images_router, prefix=api_prefix)
app.include_router(merchant_inventory_router, prefix=api_prefix)
app.include_router(merchant_warehouses_router, prefix=api_prefix)
app.include_router(merchant_tryons_router, prefix=api_prefix)
app.include_router(merchant_orders_router, prefix=api_prefix)

# Admin
app.include_router(admin_merchants_router, prefix=api_prefix)
app.include_router(admin_products_router, prefix=api_prefix)
app.include_router(admin_aimodels_router, prefix=api_prefix)
app.include_router(admin_categories_router, prefix=api_prefix)
app.include_router(admin_brands_router, prefix=api_prefix)
app.include_router(admin_orders_router, prefix=api_prefix)

@app.get("/")
def root():
    return {"app": settings.APP_NAME, "status": "running", "docs": "/docs"}

@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}
