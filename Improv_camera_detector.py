import time
import cv2
import os
import threading
import queue
import re
import pandas as pd
from collections import Counter
from fast_alpr import ALPR
import server

from improv_parking_database import (
    initialize_database,
    handle_vehicle_event,
    get_active_vehicles,
    get_today_history,
    get_available_slots,
    MAX_SLOTS,
    DB_PATH
)

initialize_database()
print(f"✅ Database at: {DB_PATH}")

flask_thread = threading.Thread(target=server.run_server, daemon=True)
flask_thread.start()
print("🌐 Flask API running on http://localhost:5000")

def fetch_live_wiki_codes():
    url = "https://en.wikipedia.org/wiki/Vehicle_registration_plates_of_India"
    try:
        tables = pd.read_html(url)
        live_codes = set()
        for df in tables:
            for col in df.columns:
                if 'Code' in str(col) or 'Two-letter code' in str(col):
                    for val in df[col].dropna():
                        val = str(val).strip()
                        if len(val) == 2 and val.isupper() and val.isalpha():
                            live_codes.add(val)
        if live_codes:
            print(f"✅ Successfully scraped {len(live_codes)} live state codes from Wikipedia!")
            return "|".join(sorted(live_codes))
    except Exception as e:
        print(f"⚠️ Wikipedia Scrape Failed ({e}). Using offline backup list.")
        
    return "AN|AP|AR|AS|BH|BR|CG|CH|DD|DL|DN|GA|GJ|HR|HP|JH|JK|KA|KL|LA|LD|MH|ML|MN|MP|MZ|NL|OD|OR|PB|PY|RJ|SK|TG|TN|TR|TS|UA|UK|UP|WB"

print("🔄 Fetching latest state codes from Wikipedia...")
state_codes = fetch_live_wiki_codes()

# ===== 1. REGEX VALIDATION =====
def is_valid_indian_plate(text):
    if len(text) < 8:
        return False
    patterns = [
        r'^(' + state_codes + r')[0-9]{2}[A-Z]{0,3}[0-9]{4}$',
        r'^T(' + state_codes + r')[0-9]{2}[A-Z]{0,3}[0-9]{4}$',
        r'^[0-9]{2}BH[0-9]{4}[A-Z]{1,3}$',
        r'^[0-9]{1,3}(CD|CC)[0-9]{1,4}$',
        r'^[0-9]{2}[A-Z][0-9]{4,6}[A-Z]$'
    ]
    for pattern in patterns:
        if re.match(pattern, text):
            return True
    return False

# ===== 2. FUZZY OCR CORRECTION =====
def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def merge_fuzzy_reads(counter, max_dist=1):
    if not counter:
        return counter
    sorted_plates = counter.most_common()
    merged_counter = Counter()
    processed = set()
    for dominant_plate, dom_count in sorted_plates:
        if dominant_plate in processed:
            continue
        merged_counter[dominant_plate] += dom_count
        processed.add(dominant_plate)
        for other_plate, other_count in sorted_plates:
            if other_plate not in processed:
                if levenshtein_distance(dominant_plate, other_plate) <= max_dist:
                    merged_counter[dominant_plate] += other_count
                    processed.add(other_plate)
    return merged_counter


# ===== 3. DUAL CAMERA CONFIGURATION =====
# 🔴 REMEMBER TO UPDATE THE IP ADDRESS WITH YOUR PHONE'S ACTUAL STREAM IP
CAMERA_CONFIGS = {
    "Webcam_Main": {"source": 0, "floor": "Ground Floor"},
    "Phone_Ramp":  {"source": "http://192.168.1.6:8080/video", "floor": "Floor 1"}
}

ai_processing_queue = queue.Queue(maxsize=4)

# Thread-safe dictionary to share frames back to the main thread for displaying
latest_display_frames = {}
frame_lock = threading.Lock()

def camera_streamer(cam_name, config):
    """Background thread that handles video capture and the motion gate."""
    source = config["source"]
    floor = config["floor"]
    
    print(f"📷 Starting stream for {cam_name} ({floor})")
    cap = cv2.VideoCapture(source)
    
    previous_frame = None
    MOTION_THRESHOLD = 15000  

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(2)
            cap = cv2.VideoCapture(source)
            continue

        # Cache the frame globally so the main thread can render it
        with frame_lock:
            latest_display_frames[cam_name] = frame.copy()

        # Motion Gate Logic
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if previous_frame is None:
            previous_frame = gray
            continue

        frame_delta = cv2.absdiff(previous_frame, gray)
        thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
        motion_level = cv2.countNonZero(thresh)
        previous_frame = gray

        # If motion is detected, send to the central AI queue
        if motion_level > MOTION_THRESHOLD:
            if not ai_processing_queue.full():
                ai_processing_queue.put((cam_name, floor, frame))

# ===== ALPR SETUP =====
alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="cct-xs-v2-global-model",
)

# Start background threads for both cameras
for name, cfg in CAMERA_CONFIGS.items():
    t = threading.Thread(target=camera_streamer, args=(name, cfg), daemon=True)
    t.start()

print("\n🚀 Multi-Camera ANPR System Active!")
print("Press ESC in any video window to stop.\n")

# ===== MULTI-CAMERA ACCUMULATION TRACKING =====
ACCUMULATION_WINDOW = 7.0
camera_sessions = {
    name: {"is_accumulating": False, "start_time": 0, "counter": Counter()}
    for name in CAMERA_CONFIGS.keys()
}

# ===== MAIN LOOP (RENDERING + AI PIPELINE) =====
while True:
    try:
        # 1. Pull and process frames from the AI processing queue
        try:
            cam_name, floor_name, frame = ai_processing_queue.get_nowait()
            
            tmp_path = f"/tmp/temp_{cam_name}.jpg"
            cv2.imwrite(tmp_path, frame)
            results = alpr.predict(tmp_path)
            
            current_frame_plates = []
            for result in results:
                if result.ocr and result.ocr.text:
                    raw_text = result.ocr.text.strip().upper()
                    plate_text = re.sub(r'[^A-Z0-9]', '', raw_text)
                    
                    if plate_text and is_valid_indian_plate(plate_text):
                        current_frame_plates.append(plate_text)

            session = camera_sessions[cam_name]
            
            if current_frame_plates:
                if not session["is_accumulating"]:
                    session["is_accumulating"] = True
                    session["start_time"] = time.time()
                    session["counter"].clear()
                    print(f"\n⏱️ [{cam_name}] Plate detected! Starting scan window...")

                for plate in current_frame_plates:
                    session["counter"][plate] += 1

        except queue.Empty:
            pass 

        # 2. Check if any camera's accumulation window has finished
        current_time = time.time()
        for cam_name, session in camera_sessions.items():
            if session["is_accumulating"]:
                elapsed = current_time - session["start_time"]

                if elapsed >= ACCUMULATION_WINDOW:
                    if session["counter"]:
                        merged_counter = merge_fuzzy_reads(session["counter"], max_dist=1)
                        best_plate, count = merged_counter.most_common(1)[0]
                        
                        if count >= 2:
                            floor_context = CAMERA_CONFIGS[cam_name]["floor"]
                            print(f"\n✅ [{cam_name}] Confirmed: {best_plate} (seen {count}x)")
                            handle_vehicle_event(best_plate, floor=floor_context)
                        else:
                            print(f"\n❌ [{cam_name}] Rejected: '{best_plate}' was only seen {count}x.")

                    session["is_accumulating"] = False
                    session["counter"].clear()
                    print(f"\n⏳ [{cam_name}] Waiting for next vehicle...\n")

        # 3. GUI Rendering (Safely handled strictly on the main thread)
        with frame_lock:
            display_copies = list(latest_display_frames.items())

        for window_name, frame_img in display_copies:
            cv2.imshow(f"Feed: {window_name}", frame_img)

        # Break out if ESC key is pressed in any window
        if cv2.waitKey(1) & 0xFF == 27:
            print("ESC pressed. Cleaning up...")
            break

    except KeyboardInterrupt:
        print("Shutting down...")
        break

cv2.destroyAllWindows()