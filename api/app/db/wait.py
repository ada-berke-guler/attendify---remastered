"""Block until PostgreSQL and Redis accept connections.  python -m app.db.wait"""
from __future__ import annotations

import logging
import sys
import time

import redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.core.config import settings

logger = logging.getLogger("attendify.wait")


def wait(timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    db_ok = redis_ok = False
    while time.monotonic() < deadline:
        if not db_ok:
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                db_ok = True
                logger.info("database is ready")
            except OperationalError:
                pass
        if not redis_ok:
            try:
                redis.Redis.from_url(settings.REDIS_URL).ping()
                redis_ok = True
                logger.info("redis is ready")
            except redis.RedisError:
                pass
        if db_ok and redis_ok:
            return True
        time.sleep(1)
    logger.error("gave up waiting (database=%s, redis=%s)", db_ok, redis_ok)
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(0 if wait() else 1)
