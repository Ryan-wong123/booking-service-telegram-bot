import asyncio
import aiosqlite

DB_PATH = "appointments.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            role TEXT
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS availability (
            staff_id INTEGER,
            date TEXT,
            time TEXT
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS appointments (
            user_id INTEGER,
            staff_id INTEGER,
            date TEXT,
            time TEXT,
            type TEXT
        )""")
        await db.commit()
    print("✅ Tables created successfully.")

asyncio.run(init_db())
