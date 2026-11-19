import asyncio

import psycopg


async def database_ready() -> bool:
    """Use libpq's PG* environment and include connection and query in one deadline."""
    try:
        async with asyncio.timeout(3):
            async with (
                await psycopg.AsyncConnection.connect(
                    connect_timeout=2, autocommit=True
                ) as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute("SELECT 1")
                return await cursor.fetchone() == (1,)
    except (psycopg.Error, TimeoutError):
        return False
