"""
Shared FastAPI dependencies — provides a cached SQLAlchemy engine instance.
"""
import sys
import os
import threading

# Allow importing project modules from the parent StatementParser directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.engine import Engine

from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
from db import create_mysql_connection, init_db_tables


def _build_engine() -> Engine:
    """
    Builds the engine and runs init_db_tables(seed=True).
    """
    engine = create_mysql_connection(
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )
    init_db_tables(engine, seed=True)
    return engine


# functools.lru_cache is NOT a mutual-exclusion primitive: it drops its own lock
# while the wrapped function runs, so N callers arriving together on a cold cache
# all execute it. That matters here because _build_engine is not just a connection
# pool - init_db_tables(seed=True) issues ~150 statements including 8 CREATE TABLE
# and 33 INSERT IGNORE. Four concurrent cold requests therefore ran DDL and seeding
# simultaneously and MySQL answered 1213 "Deadlock found when trying to get lock".
# The dashboard fires about ten endpoints at once, so this was reachable on every
# cold start rather than being a theoretical race.
#
# Locking _build_engine alone would stop the deadlock but still build one engine per
# waiting thread, each re-running init_db_tables. Double-checked locking dedupes
# properly: the fast path stays lock-free, and the build happens exactly once.
_ENGINE_LOCK = threading.Lock()
_ENGINE = None


def _create_engine() -> Engine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = _build_engine()
    return _ENGINE


def get_engine() -> Engine:
    """FastAPI dependency — returns the shared SQLAlchemy engine."""
    return _create_engine()
