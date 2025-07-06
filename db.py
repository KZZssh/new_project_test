import aiosqlite
from configs import DB_FILE

async def fetchall(query, params=None):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params or ()) as cursor:
            return await cursor.fetchall()

async def fetchone(query, params=None):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params or ()) as cursor:
            return await cursor.fetchone()

async def execute(query, params=None):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(query, params or ())
        await db.commit()
        return cursor.lastrowid

async def executemany(query, seq_of_params):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.executemany(query, seq_of_params)
        await db.commit()