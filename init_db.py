import asyncio
import aiosqlite

DB_PATH = "appointments.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS availability (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                time TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                user_id INTEGER,
                username TEXT,
                date TEXT,
                time TEXT,
                type TEXT,
                zoom_link TEXT
            )
        """)
        await db.commit()
        print("✅ Database initialized with zoom_link.")

if __name__ == "__main__":
    asyncio.run(init_db())
