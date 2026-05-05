"""Entrypoint for one-time DB setup: runs Alembic migrations then seeds data."""
import asyncio

from alembic import command
from alembic.config import Config


def run_migrations() -> None:
    cfg = Config("alembic.ini")
    print("Running migrations...")
    command.upgrade(cfg, "head")
    print("Migrations complete.")


async def run_seed() -> None:
    from database.seed import main as seed_main
    print("Seeding data...")
    await seed_main()


if __name__ == "__main__":
    run_migrations()
    asyncio.run(run_seed())
