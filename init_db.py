import asyncio
import aiosqlite

DB_PATH = "appointments.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table (optional - kept for role handling)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT
            )
        """)

        # Availability table (no staff_id)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS availability (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                time TEXT
            )
        """)

        # Appointments table (no staff_id)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                user_id INTEGER,
                username TEXT,
                date TEXT,
                time TEXT,
                type TEXT
            )
        """)

        await db.commit()
        print("✅ Database initialized without staff_id.")

if __name__ == "__main__":
    asyncio.run(init_db())
