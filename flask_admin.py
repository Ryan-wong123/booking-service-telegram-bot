from flask import Flask, render_template, request, redirect, session, url_for
import aiosqlite
import asyncio
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this!

DB_PATH = "appointments.db"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "1234"  # Change this!


# --- Routes ---

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == ADMIN_USERNAME and request.form['password'] == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect('/dashboard')
        return render_template('login.html', error="Invalid credentials.")
    return render_template('login.html')

@app.route('/calendar')
def calendar():
    if not session.get('logged_in'):
        return redirect('/')
    
    today = datetime.today()
    selected_date = request.args.get("date")

    confirmed = []
    available = []

    if selected_date:
        confirmed = asyncio.run(fetch_appointments_by_date(selected_date))
        available = asyncio.run(fetch_slots_by_date(selected_date))

    return render_template('calendar.html', today=today, confirmed=confirmed, available=available, selected_date=selected_date)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('logged_in'):
        return redirect('/')

    today = datetime.today()
    selected_date = request.args.get("date") or today.strftime('%Y-%m-%d')
    staff_filter = request.args.get("staff_id")

    if request.method == 'POST':
        staff_id = int(request.form['staff_id'])
        date = request.form['date']
        time = request.form['time']
        asyncio.run(save_slot(staff_id, date, time))
        return redirect('/dashboard')

    slots = asyncio.run(fetch_slots_by_date(selected_date, staff_filter))
    bookings = asyncio.run(fetch_appointments_by_date(selected_date, staff_filter))
    return render_template('dashboard.html',
                           today=today,
                           selected_date=selected_date,
                           staff_filter=staff_filter,
                           slots=slots,
                           bookings=bookings)

@app.route('/delete/<int:id>')
def delete_slot(id):
    if not session.get('logged_in'):
        return redirect('/')
    asyncio.run(remove_slot(id))
    return redirect('/dashboard')


# --- Database Functions ---

async def save_slot(staff_id, date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO availability (staff_id, date, time) VALUES (?, ?, ?)",
                         (staff_id, date, time))
        await db.commit()

async def fetch_slots():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, staff_id, date, time FROM availability ORDER BY date, time") as cursor:
            return await cursor.fetchall()

async def remove_slot(rowid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.commit()

async def fetch_appointments():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, staff_id, date, time, type FROM appointments ORDER BY date, time") as cursor:
            return await cursor.fetchall()
        
async def fetch_appointments_by_date(date, staff_id=None):
    query = "SELECT username, staff_id, time, type FROM appointments WHERE date = ?"
    params = [date]
    if staff_id:
        query += " AND staff_id = ?"
        params.append(staff_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query + " ORDER BY time", params) as cursor:
            return await cursor.fetchall()


async def fetch_slots_by_date(date, staff_id=None):
    query = "SELECT rowid, staff_id, time FROM availability WHERE date = ?"
    params = [date]
    if staff_id:
        query += " AND staff_id = ?"
        params.append(staff_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query + " ORDER BY time", params) as cursor:
            return await cursor.fetchall()

# --- Run App ---
if __name__ == '__main__':
    app.run(debug=True)
