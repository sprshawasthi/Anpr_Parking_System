from flask import Flask, jsonify, request
from flask_cors import CORS

from improv_parking_database import (
    handle_vehicle_event,
    get_active_vehicles,
    get_today_history,
    get_available_slots,
    MAX_SLOTS
)

app = Flask(__name__)
CORS(app)

@app.route("/api/status")
def api_status():
    """Returns live counts for the dashboard cards."""
    active = get_active_vehicles()
    occupied = len(active)
    available = get_available_slots()
    history = get_today_history()
    today_entries = len(history) + occupied

    return jsonify({
        "occupied":     occupied,
        "available":    available,
        "max_slots":    MAX_SLOTS,
        "today_entries": today_entries
    })

@app.route("/api/active")
def api_active():
    """Returns list of currently parked vehicles."""
    return jsonify(get_active_vehicles())

@app.route("/api/history")
def api_history():
    """Returns today's exit history."""
    return jsonify(get_today_history())

@app.route("/api/vehicle", methods=["POST"])
def api_vehicle():
    """
    Accepts a plate number from the dashboard's manual input.
    """
    data = request.get_json()
    plate = data.get("plate", "").strip().upper()
    if not plate:
        return jsonify({"error": "No plate provided"}), 400
    handle_vehicle_event(plate)
    return jsonify({"ok": True, "plate": plate})

def run_server():
    """Starts the Flask application."""
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)