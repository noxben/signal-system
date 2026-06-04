# signal_system/db.py
"""
Single source of truth for DB connections.
All workers import from here — never create engines independently.
"""

import os
from contextlib import contextmanager

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = (
    f"postgresql+psycopg2://"
    f"{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}"
    f"/{os.getenv('DB_NAME')}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # drops stale connections before use
    echo=False,
    connect_args={"sslmode": os.getenv("DB_SSL_MODE", "prefer")},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_db():
    """
    Usage:
        with get_db() as db:
            db.execute(text("SELECT 1"))
    Commits on clean exit, rolls back on exception.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """Quick liveness check — used by workers on startup."""
    try:
        with get_db() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
