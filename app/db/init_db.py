from app.db.engine import engine
from app.models import Base  # imports all models so metadata is populated
from app.core.logging import logger


async def init_db() -> None:
    """
    Creates all tables if they don't exist.
    Called once at application startup via lifespan.
    In production, prefer Alembic migrations over this.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified / created.")
