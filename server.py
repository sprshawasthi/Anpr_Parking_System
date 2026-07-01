import os
import json
import re
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "parking_data.json")
LOCK = threading.Lock()

last_seen = {}
COOLDOWN_SECONDS = 30 
camera_heartbeats = {}  # NEW: Tracks the last time we heard from a camera

DEFAULT_DATA = {
    "floors": [
        {"id": "hq-ground", "building": "SJVN HQ", "name": "Ground Floor", "capacity": 80},
        {"id": "hq-b1", "building": "SJVN HQ", "name": "Basement 1", "capacity": 60},
        {"id": "res-ground", "building": "Residential Complex", "name": "Ground Floor", "capacity": 50}
    ],
    "active_vehicles": [],   
    "history": [],
    "cameras": []
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return json.loads(json.dumps(DEFAULT_DATA))
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

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

def occupied_counts(data):
    counts = {}
    for v in data["active_vehicles"]:
        counts[v["floor_id"]] = counts.get(v["floor_id"], 0) + 1
    return counts

def log_vehicle_from_camera(plate, floor_id=None, is_gatekeeper=False):
    plate = plate.strip().upper()
    if not plate: return False
    
    current_time = time.time()
    if plate in last_seen and (current_time - last_seen[plate]) < COOLDOWN_SECONDS:
        return False
    last_seen[plate] = current_time
    
    with LOCK:
        data = load_data()
        existing = next((v for v in data["active_vehicles"] if v["plate_number"] == plate), None)

        if is_gatekeeper:
            if existing:
                entry_time = datetime.fromisoformat(existing["entry_time"])
                exit_time = datetime.now()
                duration_minutes = round((exit_time - entry_time).total_seconds() / 60, 1)
                data["active_vehicles"] = [v for v in data["active_vehicles"] if v["plate_number"] != plate]
                data["history"].append({
                    "plate_number": plate,
                    "entry_time": existing["entry_time"],
                    "exit_time": exit_time.isoformat(),
                    "floor_id": existing["floor_id"],
                    "duration_minutes": duration_minutes
                })
                save_data(data)
                print(f"📤 [GATEKEEPER] EXIT Logged: {plate}")
                return True
            else:
                data["active_vehicles"].append({
                    "plate_number": plate,
                    "entry_time": datetime.now().isoformat(),
                    "floor_id": floor_id
                })
                save_data(data)
                print(f"📥 [GATEKEEPER] ENTRY Logged: {plate} at floor {floor_id}")
                return True
        else:
            if existing:
                if existing["floor_id"] != floor_id:
                    old_floor = existing["floor_id"]
                    existing["floor_id"] = floor_id
                    save_data(data)
                    print(f"📍 [TRACKER] Vehicle {plate} shifted from {old_floor} to {floor_id}")
                else:
                    print(f"👁️ [TRACKER] Vehicle {plate} spotted again on {floor_id}")
            else:
                print(f"👁️ [TRACKER] Vehicle {plate} spotted on {floor_id} (No active entry record)")
            return True

@app.route("/api/floors", methods=["GET"])
def get_floors():
    with LOCK:
        data = load_data()
        counts = occupied_counts(data)
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
        data = load_data()
        if any(f["name"].lower() == name.lower() and f.get("building", "").lower() == building.lower() for f in data["floors"]):
            return jsonify({"error": "That floor already exists in that building."}), 400
            
        new_id = unique_slug(data, slugify(f"{building}-{name}"))
        data["floors"].append({"id": new_id, "building": building, "name": name, "capacity": capacity})
        save_data(data)
        return jsonify({"id": new_id, "building": building, "name": name, "capacity": capacity, "occupied": 0, "available": capacity}), 201

@app.route("/api/floors/<floor_id>", methods=["DELETE"])
def delete_floor(floor_id):
    with LOCK:
        data = load_data()
        if any(v["floor_id"] == floor_id for v in data["active_vehicles"]):
            return jsonify({"error": "Cannot remove a floor that still has vehicles parked on it."}), 400
        before = len(data["floors"])
        data["floors"] = [f for f in data["floors"] if f["id"] != floor_id]
        if len(data["floors"]) == before: return jsonify({"error": "Floor not found."}), 404
        save_data(data)
        return jsonify({"ok": True})

@app.route("/api/status", methods=["GET"])
def get_status():
    with LOCK:
        data = load_data()
        total = sum(f["capacity"] for f in data["floors"])
        occupied = len(data["active_vehicles"])
        available = max(total - occupied, 0)
        today = datetime.now().date().isoformat()
        today_entries = sum(1 for v in data["active_vehicles"] if v["entry_time"][:10] == today) + \
                        sum(1 for v in data["history"] if v["entry_time"][:10] == today)
        return jsonify({"max_slots": total, "occupied": occupied, "available": available, "today_entries": today_entries})

@app.route("/api/active", methods=["GET"])
def get_active():
    with LOCK:
        data = load_data()
        names = floor_lookup(data)
        return jsonify([{
            "plate_number": v["plate_number"],
            "entry_time": v["entry_time"],
            "floor_id": v["floor_id"],
            "floor": names.get(v["floor_id"], {}).get("name", v["floor_id"])
        } for v in data["active_vehicles"]])

@app.route("/api/history", methods=["GET"])
def get_history():
    with LOCK:
        data = load_data()
        return jsonify(list(reversed(data["history"])))

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
        data = load_data()
        data["active_vehicles"] = []
        save_data(data)
        return jsonify({"ok": True})

# ─── NEW: HEARTBEAT ROUTE ───
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
        data = load_data()
        if "cameras" not in data: data["cameras"] = []
        
        if request.method == "POST":
            body = request.get_json()
            cam_name = body["name"]
            floor_id = body["floor_id"]
            
            target_floor = next((f for f in data["floors"] if f["id"] == floor_id), None)
            building_name = target_floor.get("building", "Main Building") if target_floor else "Main Building"
            
            floor_map = {f["id"]: f.get("building", "Main Building") for f in data["floors"]}
            facility_has_camera = any(floor_map.get(c["floor_id"]) == building_name for c in data["cameras"])
            
            is_gatekeeper = not facility_has_camera
            
            existing_cam = next((c for c in data["cameras"] if c["name"] == cam_name), None)
            if existing_cam:
                existing_cam["source"] = body["source"]
                existing_cam["floor_id"] = floor_id
                existing_cam["is_gatekeeper"] = existing_cam.get("is_gatekeeper", is_gatekeeper)
            else:
                data["cameras"].append({
                    "name": cam_name,
                    "source": body["source"],
                    "floor_id": floor_id,
                    "is_gatekeeper": is_gatekeeper
                })
                
            save_data(data)
            return jsonify({"status": "success", "is_gatekeeper": is_gatekeeper}), 201
        
        # Inject live online/offline status before sending to dashboard
        now = time.time()
        for c in data["cameras"]:
            last_beat = camera_heartbeats.get(c["name"], 0)
            # If heard from in last 15 seconds, it's online
            c["status"] = "Online" if (now - last_beat) < 15 else "Offline"
            
        return jsonify(data["cameras"])

@app.route("/api/cameras/<cam_name>", methods=["DELETE"])
def delete_camera(cam_name):
    with LOCK:
        data = load_data()
        if "cameras" in data:
            data["cameras"] = [c for c in data["cameras"] if c["name"] != cam_name]
            save_data(data)
        return jsonify({"status": "deleted"}), 200

def run_server():
    load_data() 
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    run_server()