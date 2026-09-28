"""
Shared FastAPI dependencies — provides a cached SQLAlchemy engine instance.
"""
import sys
import os

# Allow importing project modules from the parent StatementParser directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.engine import Engine
from functools import lru_cache

from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
from db import create_mysql_connection, init_db_tables


@lru_cache(maxsize=1)
def _create_engine() -> Engine:
    engine = create_mysql_connection(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )
    init_db_tables(engine, seed=True)
    return engine


def get_engine() -> Engine:
    """FastAPI dependency — returns the shared SQLAlchemy engine."""
    return _create_engine()
