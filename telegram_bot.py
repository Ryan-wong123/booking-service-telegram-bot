# ========================
# telegram_bot.py (includes /help and command list on /start)
# ========================

import asyncio
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
import nest_asyncio
nest_asyncio.apply()

DB_PATH = "appointments.db"

# --- /start command ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "👋 Welcome! You can use the following commands:\n\n"
        "/book - View and book available slots\n"
        "/myappointments - View your appointments\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(message)

# --- /help command ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

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
    await update.message.reply_text("\U0001F4C5 Please select an available slot:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Confirm booking ---
async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rowid = int(query.data.split("_")[1])
    user = update.effective_user
    user_id = user.id
    username = user.username or f"id_{user_id}"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT date, time FROM availability WHERE rowid = ?", (rowid,)) as cursor:
            result = await cursor.fetchone()
            if not result:
                await query.edit_message_text("❌ Slot no longer available.")
                return

        date, time = result

        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.execute("""
            INSERT INTO appointments (user_id, username, date, time, type)
            VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, date, time, "General"))
        await db.commit()

    await query.edit_message_text(f"✅ Appointment booked for {date} at {time}.")

# --- /myappointments ---
async def my_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, date, time FROM appointments WHERE user_id = ?", (user_id,)) as cursor:
            appts = await cursor.fetchall()

    if not appts:
        await update.message.reply_text("You have no confirmed appointments.")
        return

    keyboard = [
        [InlineKeyboardButton(f"{date} at {time} ❌ Cancel", callback_data=f"cancel_{rowid}")]
        for rowid, date, time in appts
    ]
    await update.message.reply_text("🗓️ Your Appointments:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- Cancel appointment ---
async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rowid = int(query.data.split("_")[1])

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT date, time FROM appointments WHERE rowid = ?", (rowid,)) as cursor:
            result = await cursor.fetchone()
            if not result:
                await query.edit_message_text("❌ Appointment not found.")
                return
        date, time = result

        await db.execute("DELETE FROM appointments WHERE rowid = ?", (rowid,))
        await db.execute("INSERT INTO availability (date, time) VALUES (?, ?)", (date, time))
        await db.commit()

    await query.edit_message_text(f"🗑️ Your appointment on {date} at {time} has been cancelled.")

# --- Bot runner ---
async def main():
    app = ApplicationBuilder().token("7086293632:AAHbp_uUi0AJ9EeJWQ8lSpp9yvAJBiKFZD8").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("book", book))
    app.add_handler(CommandHandler("myappointments", my_appointments))
    app.add_handler(CallbackQueryHandler(confirm_booking, pattern=r"^book_"))
    app.add_handler(CallbackQueryHandler(cancel_appointment, pattern=r"^cancel_"))

    print("🤖 Telegram bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
