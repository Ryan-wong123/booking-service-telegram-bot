import asyncio
import aiosqlite

DB_PATH = "appointments.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Users table (used to store staff/customer roles)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT
            )
        """)

        # Availability table (available time slots set by staff via Flask)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS availability (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER,
                date TEXT,
                time TEXT
            )
        """)

        # Appointments table (booked slots, confirmed via Telegram)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                user_id INTEGER,
                username TEXT,
                staff_id INTEGER,
                date TEXT,
                time TEXT,
                type TEXT
            )
        """)

        await db.commit()
        print("✅ Database initialized successfully.")

# Run it
if __name__ == "__main__":
    asyncio.run(init_db())
