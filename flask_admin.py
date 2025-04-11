from flask import Flask, render_template, request, redirect, session, url_for
import aiosqlite
import asyncio

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

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('logged_in'):
        return redirect('/')

    if request.method == 'POST':
        staff_id = int(request.form['staff_id'])
        date = request.form['date']
        time = request.form['time']
        asyncio.run(save_slot(staff_id, date, time))
        return redirect('/dashboard')

    slots = asyncio.run(fetch_slots())
    bookings = asyncio.run(fetch_appointments())
    return render_template('dashboard.html', slots=slots, bookings=bookings)


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


# --- Run App ---
if __name__ == '__main__':
    app.run(debug=True)
