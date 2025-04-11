# flask_admin.py (cleans selected_date on month/year filtering and post submission)

from flask import Flask, render_template, request, redirect, session, url_for
import aiosqlite
import asyncio
from datetime import datetime
from collections import defaultdict
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DB_PATH = "appointments.db"

# --- Login protection decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == '1234':
            session['logged_in'] = True
            return redirect('/dashboard')
        return render_template('login.html', error="Invalid credentials.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    category = request.args.get("category", "both")
    selected_date = request.args.get("selected_date") or None
    month_year = request.args.get("month_year")

    if month_year:
        year, month = map(int, month_year.split("-"))
    else:
        today_dt = datetime.today()
        year = today_dt.year
        month = today_dt.month

    today = datetime(year, month, 1)

    if request.method == 'POST':
        date = request.form['date']
        time = request.form['time']
        asyncio.run(save_slot(date, time))
        return redirect(f"/dashboard?category={category}&month_year={year:04d}-{month:02d}")  # clear selected_date

    all_slots = asyncio.run(fetch_all_slots())
    all_bookings = asyncio.run(fetch_all_appointments())

    def date_matches_month(date_str, year, month):
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            return d.year == year and d.month == month
        except:
            return False

    slots = []
    if category in ["both", "available"]:
        if selected_date:
            slots = [s for s in all_slots if s[1] == selected_date]
        else:
            slots = [s for s in all_slots if date_matches_month(s[1], year, month)]

    bookings = []
    if category in ["both", "confirmed"]:
        if selected_date:
            bookings = [b for b in all_bookings if b[1] == selected_date]
        else:
            bookings = [b for b in all_bookings if date_matches_month(b[1], year, month)]

    date_status = asyncio.run(get_date_status_map())

    return render_template("dashboard.html",
                           slots=slots,
                           bookings=bookings,
                           category=category,
                           today=today,
                           selected_date=selected_date,
                           month=month,
                           year=year,
                           date_status=date_status)

@app.route('/delete/<int:id>')
@login_required
def delete_slot(id):
    asyncio.run(remove_slot(id))
    return redirect('/dashboard')

# --- DB Functions ---
async def save_slot(date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO availability (date, time) VALUES (?, ?)", (date, time))
        await db.commit()

async def remove_slot(rowid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.commit()

async def fetch_all_appointments():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT username, date, time, type FROM appointments ORDER BY date, time") as cursor:
            return await cursor.fetchall()

async def fetch_all_slots():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, date, time FROM availability ORDER BY date, time") as cursor:
            return await cursor.fetchall()

async def get_date_status_map():
    async with aiosqlite.connect(DB_PATH) as db:
        confirmed = defaultdict(int)
        async with db.execute("SELECT date FROM appointments") as cursor:
            async for row in cursor:
                confirmed[row[0]] += 1

        available = defaultdict(int)
        async with db.execute("SELECT date FROM availability") as cursor:
            async for row in cursor:
                available[row[0]] += 1

    date_status = {}
    all_dates = set(confirmed.keys()) | set(available.keys())
    for date in all_dates:
        booked = confirmed.get(date, 0)
        slots = confirmed.get(date, 0) + available.get(date, 0)
        if slots == 0:
            date_status[date] = "green"
        else:
            ratio = booked / slots
            if ratio == 0:
                date_status[date] = "green"
            elif ratio < 1:
                date_status[date] = "yellow"
            else:
                date_status[date] = "red"
    return date_status

if __name__ == '__main__':
    app.run(debug=True)
