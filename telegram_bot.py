import asyncio
import aiosqlite
import httpx
import base64
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
import nest_asyncio
import subprocess
nest_asyncio.apply()

DB_PATH = "appointments.db"
ADMIN_DB = "admin_ids.txt"

# --- Admin ID Management ---
def get_admin_ids():
    try:
        with open(ADMIN_DB, 'r') as f:
            return [int(line.strip()) for line in f if line.strip().isdigit()]
    except:
        return []

def save_admin_id(admin_id):
    current_ids = set(get_admin_ids())
    if admin_id not in current_ids:
        with open(ADMIN_DB, 'a') as f:
            f.write(f"{admin_id}\n")

# --- Zoom Token and Meeting ---
async def get_zoom_access_token():
    account_id = "7IQUuPaTSnGp5EQNffN56Q"
    client_id = "7GT3z8YGTJVInSSRAvr4Q"
    client_secret = "9JHQIvCmbmJZWYiVuxicAch21h0fNCUW"

    basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {basic_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "account_credentials",
        "account_id": account_id
    }

    async with httpx.AsyncClient() as client:
        response = await client.post("https://zoom.us/oauth/token", data=data, headers=headers)
        response.raise_for_status()
        return response.json()["access_token"]

async def create_zoom_meeting():
    access_token = await get_zoom_access_token()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "topic": "Scheduled Appointment",
        "type": 1
    }
    async with httpx.AsyncClient() as client:
        response = await client.post("https://api.zoom.us/v2/users/me/meetings", headers=headers, json=payload)
        data = response.json()
        return data.get("join_url", "")

# --- Reminder ---
async def schedule_reminder(bot, user_id, date_str, time_str, scheduler):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    remind_at = dt - timedelta(minutes=30)
    if remind_at > datetime.now():
        scheduler.add_job(
            bot.send_message,
            'date',
            run_date=remind_at,
            args=[user_id, f"⏰ Reminder: You have an appointment today at {time_str}."]
        )

# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = (
        "👋 Welcome! You can use the following commands:\n\n"
        "/book - View and book available slots\n"
        "/myappointments - View your appointments\n"
        "/help - Show this help message\n"
    )
    await update.message.reply_text(message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def register_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    save_admin_id(admin_id)
    await update.message.reply_text(f"✅ You have been added to the admin list. Your user ID is {admin_id}.")

async def book(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, date, time FROM availability ORDER BY date, time") as cursor:
            slots = await cursor.fetchall()
    if not slots:
        await update.message.reply_text("No available slots right now.")
        return
    keyboard = [[InlineKeyboardButton(f"{date} at {time}", callback_data=f"book_{rowid}")] for rowid, date, time in slots]
    await update.message.reply_text("📅 Please select an available slot:", reply_markup=InlineKeyboardMarkup(keyboard))

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
        zoom_link = await create_zoom_meeting()
        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.execute("""
            INSERT INTO appointments (user_id, username, date, time, type, zoom_link)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, username, date, time, "General", zoom_link))
        await db.commit()

    await query.edit_message_text(f"✅ Appointment booked for {date} at {time}.\n🔗 Zoom Link: {zoom_link}")
    await schedule_reminder(context.bot, user_id, date, time, context.application.scheduler)
    for admin_id in get_admin_ids():
        await context.bot.send_message(chat_id=admin_id, text=f"📌 New Booking:\nUser @{username} booked {date} at {time}.\n🔗 Zoom: {zoom_link}")

async def my_appointments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, date, time FROM appointments WHERE user_id = ?", (user_id,)) as cursor:
            appts = await cursor.fetchall()
    if not appts:
        await update.message.reply_text("You have no confirmed appointments.")
        return
    keyboard = [[InlineKeyboardButton(f"{date} at {time} ❌ Cancel", callback_data=f"cancel_{rowid}")] for rowid, date, time in appts]
    await update.message.reply_text("🗓️ Your Appointments:", reply_markup=InlineKeyboardMarkup(keyboard))

async def cancel_appointment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rowid = int(query.data.split("_")[1])
    user = update.effective_user
    username = user.username or f"id_{user.id}"
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
    for admin_id in get_admin_ids():
        await context.bot.send_message(chat_id=admin_id, text=f"❌ Cancellation:\nUser @{username} cancelled {date} at {time}.")

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.start()
    app = ApplicationBuilder().token("7086293632:AAHbp_uUi0AJ9EeJWQ8lSpp9yvAJBiKFZD8").build()
    app.scheduler = scheduler
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("book", book))
    app.add_handler(CommandHandler("myappointments", my_appointments))
    app.add_handler(CommandHandler("registeradmin", register_admin))
    app.add_handler(CallbackQueryHandler(confirm_booking, pattern=r"^book_"))
    app.add_handler(CallbackQueryHandler(cancel_appointment, pattern=r"^cancel_"))
    print("🤖 Telegram bot is running...")
    await app.run_polling()

if __name__ == "__main__":
    subprocess.run(["python", "init_db.py"])
    asyncio.run(main())
