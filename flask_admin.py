from flask import Flask, render_template, request, redirect, session, url_for
import aiosqlite
import asyncio
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DB_PATH = "appointments.db"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Login ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == '1234':
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid credentials.")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- Dashboard View ---
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if not session.get('logged_in'):
        return redirect('/')

    today = datetime.today()
    selected_date = request.args.get("date") or today.strftime('%Y-%m-%d')

    if request.method == 'POST':
        date = request.form['date']
        time = request.form['time']
        asyncio.run(save_slot(date, time))
        return redirect('/dashboard')

    slots = asyncio.run(fetch_slots_by_date(selected_date))
    bookings = asyncio.run(fetch_appointments_by_date(selected_date))
    return render_template('dashboard.html', today=today, selected_date=selected_date, slots=slots, bookings=bookings)

@app.route('/delete/<int:id>')
@login_required
def delete_slot(id):
    if not session.get('logged_in'):
        return redirect('/')
    asyncio.run(remove_slot(id))
    return redirect('/dashboard')

# --- DB Functions ---
async def save_slot(date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO availability (date, time) VALUES (?, ?)", (date, time))
        await db.commit()

async def fetch_slots_by_date(date):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rowid, time FROM availability WHERE date = ? ORDER BY time", (date,)) as cursor:
            return await cursor.fetchall()

async def remove_slot(rowid):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM availability WHERE rowid = ?", (rowid,))
        await db.commit()

async def fetch_appointments_by_date(date):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT username, time, type FROM appointments WHERE date = ? ORDER BY time", (date,)) as cursor:
            return await cursor.fetchall()

if __name__ == '__main__':
    app.run(debug=True)
