import os
import json
import re
import threading
import time
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "parking_data.json")
DB_PATH = os.path.join(SCRIPT_DIR, "parking.db")
LOCK = threading.Lock()

last_seen = {}
# NOTE: The 30-second cooldown prevents the camera from instantly toggling 
# the car back and forth if it drives slowly past the lens.
COOLDOWN_SECONDS = 30 
camera_heartbeats = {}

# ─── 1. SQLITE DATABASE SETUP ───
def initialize_database():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_parking (
            plate_number TEXT PRIMARY KEY,
            entry_time   TEXT NOT NULL,
            floor_id     TEXT
        )
    """)
    
    # Safely upgrade the database to remember previous floors
    c.execute("PRAGMA table_info(active_parking)")
    columns = [row[1] for row in c.fetchall()]
    if "previous_floor_id" not in columns:
        c.execute("ALTER TABLE active_parking ADD COLUMN previous_floor_id TEXT")
        
    c.execute("""
        CREATE TABLE IF NOT EXISTS parking_history (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            plate_number     TEXT NOT NULL,
            entry_time       TEXT NOT NULL,
            exit_time        TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            floor_id         TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── 2. JSON CONFIG SETUP ───
DEFAULT_CONFIG = {
    "floors": [
        {"id": "hq-ground", "building": "SJVN HQ", "name": "Ground Floor", "capacity": 80},
        {"id": "hq-b1", "building": "SJVN HQ", "name": "Basement 1", "capacity": 60}
    ],
    "cameras": []
}

def load_config():
    if not os.path.exists(DATA_FILE):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
        return {"floors": data.get("floors", []), "cameras": data.get("cameras", [])}

def save_config(data):
    clean_data = {"floors": data.get("floors", []), "cameras": data.get("cameras", [])}
    with open(DATA_FILE, "w") as f:
        json.dump(clean_data, f, indent=2)

def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "floor"

def unique_slug(data, base):
    existing = {f["id"] for f in data["floors"]}
    slug = base
    n = 2
    while slug in existing:
        slug = f"{base}-{n}"
        n += 1
    return slug

def floor_lookup(data):
    return {f["id"]: f for f in data["floors"]}

def occupied_counts():
    conn = get_db_connection()
    counts = {}
    for row in conn.execute("SELECT floor_id, COUNT(*) as count FROM active_parking GROUP BY floor_id"):
        counts[row["floor_id"]] = row["count"]
    conn.close()
    return counts

# ─── 3. CORE LOGIC (Hybrid Processing with Re-detection Shift) ───
def log_vehicle_from_camera(plate, floor_id=None, is_gatekeeper=False):
    plate = plate.strip().upper()
    if not plate: return False
    
    current_time_sec = time.time()
    if plate in last_seen and (current_time_sec - last_seen[plate]) < COOLDOWN_SECONDS:
        return False
    last_seen[plate] = current_time_sec
    
    current_time = datetime.now()
    current_time_str = current_time.isoformat()
    
    with LOCK:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Now fetches previous_floor_id as well
        c.execute("SELECT entry_time, floor_id, previous_floor_id FROM active_parking WHERE plate_number = ?", (plate,))
        existing = c.fetchone()

        if is_gatekeeper:
            if existing:
                # Handle Exit
                entry_time_str = existing["entry_time"]
                entry_dt = datetime.fromisoformat(entry_time_str)
                duration_minutes = round((current_time - entry_dt).total_seconds() / 60, 1)
                
                c.execute("DELETE FROM active_parking WHERE plate_number = ?", (plate,))
                c.execute("""
                    INSERT INTO parking_history (plate_number, entry_time, exit_time, duration_minutes, floor_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (plate, entry_time_str, current_time_str, duration_minutes, existing["floor_id"]))
                conn.commit()
                print(f"📤 [GATEKEEPER] EXIT Logged: {plate}")
            else:
                # Handle Entry (Initializes previous_floor_id as NULL)
                c.execute("INSERT INTO active_parking (plate_number, entry_time, floor_id, previous_floor_id) VALUES (?, ?, ?, NULL)", 
                          (plate, current_time_str, floor_id))
                conn.commit()
                print(f"📥 [GATEKEEPER] ENTRY Logged: {plate} at floor {floor_id}")
        else:
            if existing:
                current_floor = existing["floor_id"]
                prev_floor = existing["previous_floor_id"]
                
                if current_floor != floor_id:
                    # The car arrived at a new tracker floor
                    c.execute("UPDATE active_parking SET floor_id = ?, previous_floor_id = ? WHERE plate_number = ?", 
                              (floor_id, current_floor, plate))
                    conn.commit()
                    print(f"📍 [TRACKER] Vehicle {plate} shifted from {current_floor} to {floor_id}")
                else:
                    # The car was re-detected on the SAME floor it is already parked on
                    if prev_floor:
                        # Swap the floors to bounce it backward
                        c.execute("UPDATE active_parking SET floor_id = ?, previous_floor_id = ? WHERE plate_number = ?", 
                                  (prev_floor, current_floor, plate))
                        conn.commit()
                        print(f"🔄 [TRACKER] Vehicle {plate} re-detected! Bouncing back from {current_floor} to {prev_floor}")
                    else:
                        print(f"👁️ [TRACKER] Vehicle {plate} spotted again on {floor_id} (No previous floor known to bounce to)")
            else:
                # Ghost Protocol: The gate missed it, but a tracker caught it. Force an entry.
                c.execute("INSERT INTO active_parking (plate_number, entry_time, floor_id, previous_floor_id) VALUES (?, ?, ?, NULL)", 
                          (plate, current_time_str, floor_id))
                conn.commit()
                print(f"👻 [TRACKER] GHOST ENTRY Logged: {plate} missed by gate, found on {floor_id}")
        
        conn.close()
        return True

# ─── 4. API ROUTES ───
@app.route("/api/floors", methods=["GET"])
def get_floors():
    with LOCK:
        data = load_config()
        counts = occupied_counts()
        result = []
        for f in data["floors"]:
            occupied = counts.get(f["id"], 0)
            result.append({
                "id": f["id"],
                "building": f.get("building", "Main Building"),
                "name": f["name"],
                "capacity": f["capacity"],
                "occupied": occupied,
                "available": max(f["capacity"] - occupied, 0)
            })
        return jsonify(result)

@app.route("/api/floors", methods=["POST"])
def add_floor():
    body = request.get_json(force=True, silent=True) or {}
    building = (body.get("building") or "Main Building").strip()
    name = (body.get("name") or "").strip()
    capacity = body.get("capacity")

    if not name: return jsonify({"error": "Floor name is required."}), 400
    try:
        capacity = int(capacity)
        if capacity <= 0: raise ValueError
    except: return jsonify({"error": "Capacity must be a positive number."}), 400

    with LOCK:
        data = load_config()
        if any(f["name"].lower() == name.lower() and f.get("building", "").lower() == building.lower() for f in data["floors"]):
            return jsonify({"error": "That floor already exists in that building."}), 400
            
        new_id = unique_slug(data, slugify(f"{building}-{name}"))
        data["floors"].append({"id": new_id, "building": building, "name": name, "capacity": capacity})
        save_config(data)
        return jsonify({"id": new_id, "building": building, "name": name, "capacity": capacity, "occupied": 0, "available": capacity}), 201

@app.route("/api/floors/<floor_id>", methods=["DELETE"])
def delete_floor(floor_id):
    with LOCK:
        data = load_config()
        counts = occupied_counts()
        if counts.get(floor_id, 0) > 0:
            return jsonify({"error": "Cannot remove a floor that still has vehicles parked on it."}), 400
        
        before = len(data["floors"])
        data["floors"] = [f for f in data["floors"] if f["id"] != floor_id]
        if len(data["floors"]) == before: return jsonify({"error": "Floor not found."}), 404
        save_config(data)
        return jsonify({"ok": True})

@app.route("/api/status", methods=["GET"])
def get_status():
    with LOCK:
        data = load_config()
        total = sum(f["capacity"] for f in data["floors"])
        
        conn = get_db_connection()
        occupied = conn.execute("SELECT COUNT(*) FROM active_parking").fetchone()[0]
        
        today = datetime.now().date().isoformat()
        today_active = conn.execute("SELECT COUNT(*) FROM active_parking WHERE entry_time LIKE ?", (today + "%",)).fetchone()[0]
        today_history = conn.execute("SELECT COUNT(*) FROM parking_history WHERE entry_time LIKE ?", (today + "%",)).fetchone()[0]
        conn.close()
        
        available = max(total - occupied, 0)
        today_entries = today_active + today_history
        
        return jsonify({"max_slots": total, "occupied": occupied, "available": available, "today_entries": today_entries})

@app.route("/api/active", methods=["GET"])
def get_active():
    with LOCK:
        data = load_config()
        names = floor_lookup(data)
        
        conn = get_db_connection()
        rows = conn.execute("SELECT plate_number, entry_time, floor_id FROM active_parking ORDER BY entry_time DESC").fetchall()
        conn.close()
        
        return jsonify([{
            "plate_number": r["plate_number"],
            "entry_time": r["entry_time"],
            "floor_id": r["floor_id"],
            "floor": names.get(r["floor_id"], {}).get("name", r["floor_id"])
        } for r in rows])

@app.route("/api/history", methods=["GET"])
def get_history():
    with LOCK:
        conn = get_db_connection()
        rows = conn.execute("SELECT plate_number, entry_time, exit_time, duration_minutes, floor_id FROM parking_history ORDER BY id DESC").fetchall()
        conn.close()
        
        return jsonify([{
            "plate_number": r["plate_number"],
            "entry_time": r["entry_time"],
            "exit_time": r["exit_time"],
            "duration_minutes": r["duration_minutes"],
            "floor_id": r["floor_id"]
        } for r in rows])

@app.route("/api/vehicle", methods=["POST"])
def detect_vehicle_api():
    body = request.get_json(force=True, silent=True) or {}
    plate = body.get("plate", "")
    floor_id = body.get("floor_id")
    is_gate = body.get("is_gatekeeper", False)
    log_vehicle_from_camera(plate, floor_id, is_gate)
    return jsonify({"ok": True})

@app.route("/api/reset", methods=["POST"])
def reset_active():
    with LOCK:
        conn = get_db_connection()
        conn.execute("DELETE FROM active_parking")
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

@app.route("/api/cameras/heartbeat", methods=["POST"])
def camera_heartbeat():
    body = request.get_json(force=True, silent=True) or {}
    cam_name = body.get("name")
    if cam_name:
        camera_heartbeats[cam_name] = time.time()
    return jsonify({"ok": True})

@app.route("/api/cameras", methods=["GET", "POST"])
def manage_cameras():
    with LOCK:
        data = load_config()
        if "cameras" not in data: data["cameras"] = []
        
        if request.method == "POST":
            body = request.get_json()
            cam_name = body["name"]
            floor_id = body["floor_id"]
            
            target_floor = next((f for f in data["floors"] if f["id"] == floor_id), None)
            target_building = target_floor.get("building", "Main Building") if target_floor else "Main Building"
            target_building_clean = target_building.strip().lower()
            
            building_has_gatekeeper = False
            for c in data["cameras"]:
                if c["name"] == cam_name:
                    continue
                    
                c_floor = next((f for f in data["floors"] if f["id"] == c["floor_id"]), None)
                c_building = c_floor.get("building", "Main Building") if c_floor else "Main Building"
                c_building_clean = c_building.strip().lower()
                
                if c_building_clean == target_building_clean and c.get("is_gatekeeper"):
                    building_has_gatekeeper = True
                    break
            
            is_gatekeeper = not building_has_gatekeeper
            
            existing_cam = next((c for c in data["cameras"] if c["name"] == cam_name), None)
            if existing_cam:
                existing_cam["source"] = body["source"]
                existing_cam["floor_id"] = floor_id
                existing_cam["is_gatekeeper"] = is_gatekeeper
            else:
                data["cameras"].append({
                    "name": cam_name,
                    "source": body["source"],
                    "floor_id": floor_id,
                    "is_gatekeeper": is_gatekeeper
                })
                
            save_config(data)
            return jsonify({"status": "success", "is_gatekeeper": is_gatekeeper}), 201
        
        now = time.time()
        for c in data["cameras"]:
            last_beat = camera_heartbeats.get(c["name"], 0)
            c["status"] = "Online" if (now - last_beat) < 15 else "Offline"
            
        return jsonify(data["cameras"])

@app.route("/api/cameras/<cam_name>", methods=["DELETE"])
def delete_camera(cam_name):
    with LOCK:
        data = load_config()
        data["cameras"] = [c for c in data["cameras"] if c["name"] != cam_name]
        save_config(data)
        return jsonify({"status": "deleted"}), 200

def run_server():
    initialize_database()
    load_config() 
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_server()