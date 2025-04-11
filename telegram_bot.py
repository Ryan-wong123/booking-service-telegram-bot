import asyncio
import nest_asyncio  # 👈 required to allow nested event loops
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Patch the event loop to allow nested running (important fix!)
nest_asyncio.apply()

DB_PATH = "appointments.db"

# --- /book command ---
async def book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, date, time FROM availability ORDER BY date, time") as cursor:
            slots = await cursor.fetchall()

    if not slots:
        await update.message.reply_text("No available slots right now.")
        return

    keyboard = [
        [InlineKeyboardButton(f"{date} at {time}", callback_data=f"book_{rowid}")]
        for rowid, date, time in slots
    ]
    await update.message.reply_text("📅 Please select an available slot:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Confirm booking callback ---
async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rowid = int(query.data.split("_")[1])
    user_id = query.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT staff_id, date, time FROM availability WHERE rowid = ?", (rowid,)) as cursor:
            result = await cursor.fetchone()
            if not result:
                await query.edit_message_text("❌ Slot no longer available.")
                return

        staff_id, date, time = result
        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.execute("INSERT INTO appointments (user_id, staff_id, date, time, type) VALUES (?, ?, ?, ?, ?)",
                         (user_id, staff_id, date, time, "General"))
        await db.commit()

    await query.edit_message_text(f"✅ Your appointment is booked for {date} at {time} with staff {staff_id}.")

async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rowid = int(query.data.split("_")[1])
    user = update.effective_user
    user_id = user.id
    username = user.username or f"id_{user_id}"

    async with aiosqlite.connect("appointments.db") as db:
        async with db.execute("SELECT staff_id, date, time FROM availability WHERE rowid = ?", (rowid,)) as cursor:
            result = await cursor.fetchone()
            if not result:
                await query.edit_message_text("❌ Slot no longer available.")
                return

        staff_id, date, time = result

        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.execute("""
            INSERT INTO appointments (user_id, username, staff_id, date, time, type)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, staff_id, date, time, "General"))
        await db.commit()

    await query.edit_message_text(f"✅ Appointment booked for {date} at {time} with staff {staff_id}.")

# --- Setup and run bot ---
async def setup_bot():
    app = ApplicationBuilder().token("7086293632:AAHbp_uUi0AJ9EeJWQ8lSpp9yvAJBiKFZD8").build()

    app.add_handler(CommandHandler("book", book))
    app.add_handler(CallbackQueryHandler(confirm_booking, pattern=r"^book_"))

    print("🤖 Telegram bot is running...")
    await app.run_polling()

# Run inside patched event loop
asyncio.get_event_loop().run_until_complete(setup_bot())
