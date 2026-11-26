import asyncio
import os

import psycopg


async def database_ready() -> bool:
    """Verify the API login can read the project schema within one deadline."""
    password = os.environ.get("SENTINEL_APP_PASSWORD")
    if not password:
        return False
    try:
        async with asyncio.timeout(3):
            async with (
                await psycopg.AsyncConnection.connect(
                    user="sentinel_app", password=password, connect_timeout=2, autocommit=True
                ) as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute("SELECT id FROM public.projects LIMIT 0")
                return True
    except (psycopg.Error, TimeoutError):
        return False
