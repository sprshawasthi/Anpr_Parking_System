import os
import time
import datetime
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MAX_SLOTS = 200

SCAN_COOLDOWN = 15.0

DB_PATH = os.path.join(SCRIPT_DIR, "parking.db")

last_scans = {}

def initialize_database():
    """Creates the SQLite database and tables if they don't exist."""
    print(f"📂 Using database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Active vehicles currently parked
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_parking (
            plate_number TEXT PRIMARY KEY,
            entry_time   TEXT NOT NULL
        )
    """)

    # Full history of all entries and exits
    c.execute("""
        CREATE TABLE IF NOT EXISTS parking_history (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number     TEXT    NOT NULL,
            entry_time       TEXT    NOT NULL,
            exit_time        TEXT    NOT NULL,
            duration_minutes INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialized.")


def get_connection():
    """Returns a fresh SQLite connection."""
    return sqlite3.connect(DB_PATH)


# ===== SLOT STATUS =====

def get_available_slots():
    """Returns how many slots are still free."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM active_parking")
    active_count = c.fetchone()[0]
    conn.close()
    return max(0, MAX_SLOTS - active_count)


def get_active_vehicles():
    """Returns list of currently parked vehicles as dicts."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT plate_number, entry_time FROM active_parking ORDER BY entry_time")
    rows = c.fetchall()
    conn.close()
    return [{"plate_number": r[0], "entry_time": r[1]} for r in rows]


def get_today_history():
    """Returns today's parking history as list of dicts."""
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, plate_number, entry_time, exit_time, duration_minutes
        FROM parking_history
        WHERE entry_time LIKE ?
        ORDER BY id DESC
    """, (today_str + "%",))
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "plate_number": r[1],
            "entry_time": r[2],
            "exit_time": r[3],
            "duration_minutes": r[4]
        }
        for r in rows
    ]


# ===== VEHICLE EVENT =====

def handle_vehicle_event(plate_number):
    """Handles both vehicle entry and exit using the SQLite database."""
    global last_scans

    plate_number = plate_number.strip().upper().replace(" ", "")

    if not plate_number:
        print("❌ Invalid plate detected.")
        return

    current_timestamp = time.time()

    # Cooldown check — ignore duplicate scans within SCAN_COOLDOWN seconds
    if plate_number in last_scans:
        elapsed = current_timestamp - last_scans[plate_number]
        if elapsed < SCAN_COOLDOWN:
            print(
                f"⏳ Duplicate scan ignored for {plate_number}. "
                f"Cooldown active ({elapsed:.1f}s elapsed)."
            )
            return

    last_scans[plate_number] = current_timestamp

    current_time = datetime.datetime.now()
    current_time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    c = conn.cursor()

    # Check if vehicle is already parked
    c.execute("SELECT entry_time FROM active_parking WHERE plate_number = ?", (plate_number,))
    row = c.fetchone()

    if row:
        # --- EXIT ---
        entry_time_str = row[0]
        entry_time = datetime.datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
        duration_minutes = int((current_time - entry_time).total_seconds() / 60)

        # Remove from active
        c.execute("DELETE FROM active_parking WHERE plate_number = ?", (plate_number,))

        # Add to history
        c.execute("""
            INSERT INTO parking_history (plate_number, entry_time, exit_time, duration_minutes)
            VALUES (?, ?, ?, ?)
        """, (plate_number, entry_time_str, current_time_str, duration_minutes))

        conn.commit()
        conn.close()

        print(f"\n🚗 VEHICLE EXIT")
        print(f"Plate       : {plate_number}")
        print(f"Exit Time   : {current_time_str}")
        print(f"Duration    : {duration_minutes} minutes")

    else:
        # --- ENTRY ---
        c.execute("SELECT COUNT(*) FROM active_parking")
        active_count = c.fetchone()[0]

        if active_count >= MAX_SLOTS:
            conn.close()
            print(f"\n⚠️ PARKING FULL! Entry denied for {plate_number}")
            return

        c.execute(
            "INSERT INTO active_parking (plate_number, entry_time) VALUES (?, ?)",
            (plate_number, current_time_str)
        )
        conn.commit()
        conn.close()

        print(f"\n📥 VEHICLE ENTRY")
        print(f"Plate       : {plate_number}")
        print(f"Entry Time  : {current_time_str}")

    available = get_available_slots()
    print(f"📊 Available Slots: {available}/{MAX_SLOTS}")


if __name__ == "__main__":
    initialize_database()