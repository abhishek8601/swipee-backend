import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger("swipee.database")

Base = declarative_base()

# Attempt primary database connection (MySQL)
engine = None
try:
    if settings.DB_CONNECTION == "mysql":
        test_engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        # Test connection quickly
        with test_engine.connect() as conn:
            pass
        engine = test_engine
        logger.info(f"Connected to MySQL at {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_DATABASE}")
except Exception as e:
    logger.warning(f"Failed to connect to MySQL ({e}).")
    if settings.USE_SQLITE_FALLBACK:
        sqlite_url = f"sqlite:///{settings.BASE_DIR}/swipee.db"
        logger.info(f"Falling back to local SQLite database: {sqlite_url}")
        engine = create_engine(
            sqlite_url,
            connect_args={"check_same_thread": False},
        )
    else:
        raise

if engine is None:
    sqlite_url = f"sqlite:///{settings.BASE_DIR}/swipee.db"
    engine = create_engine(
        sqlite_url,
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
