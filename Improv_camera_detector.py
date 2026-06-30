import time
import cv2
import threading
import queue
import re
import pandas as pd
from collections import Counter
from fast_alpr import ALPR
import server

# ===== INIT FLASK SERVER =====
flask_thread = threading.Thread(target=server.run_server, daemon=True)
flask_thread.start()
print("🌐 Unified JSON Server running on http://localhost:5000")

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
            print(f"✅ Scraped {len(live_codes)} state codes from Wikipedia!")
            return "|".join(sorted(live_codes))
    except Exception:
        pass
    return "AN|AP|AR|AS|BH|BR|CG|CH|DD|DL|DN|GA|GJ|HR|HP|JH|JK|KA|KL|LA|LD|MH|ML|MN|MP|MZ|NL|OD|OR|PB|PY|RJ|SK|TG|TN|TR|TS|UA|UK|UP|WB"

state_codes = fetch_live_wiki_codes()

def is_valid_indian_plate(text):
    if len(text) < 8: return False
    patterns = [
        r'^(' + state_codes + r')[0-9]{2}[A-Z]{0,3}[0-9]{4}$',
        r'^T(' + state_codes + r')[0-9]{2}[A-Z]{0,3}[0-9]{4}$',
        r'^[0-9]{2}BH[0-9]{4}[A-Z]{1,3}$',
        r'^[0-9]{1,3}(CD|CC)[0-9]{1,4}$',
        r'^[0-9]{2}[A-Z][0-9]{4,6}[A-Z]$'
    ]
    return any(re.match(pattern, text) for pattern in patterns)

def merge_fuzzy_reads(counter, max_dist=1):
    def levenshtein(s1, s2):
        if len(s1) < len(s2): return levenshtein(s2, s1)
        if len(s2) == 0: return len(s1)
        prev = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
            prev = curr
        return prev[-1]
    
    if not counter: return counter
    sorted_plates = counter.most_common()
    merged = Counter()
    processed = set()
    for dom_p, dom_c in sorted_plates:
        if dom_p in processed: continue
        merged[dom_p] += dom_c
        processed.add(dom_p)
        for oth_p, oth_c in sorted_plates:
            if oth_p not in processed and levenshtein(dom_p, oth_p) <= max_dist:
                merged[dom_p] += oth_c
                processed.add(oth_p)
    return merged

# 🔴 UPDATE PHONE IP HERE! floor_id must match the IDs created in your dashboard
CAMERA_CONFIGS = {
    "Webcam_Main": {"source": 0, "floor_id": "hq-ground"},
    "Phone_Ramp":  {"source": "http://192.168.1.6:8080/video", "floor_id": "hq-b1"}
}

ai_processing_queue = queue.Queue(maxsize=4)
latest_display_frames = {}
frame_lock = threading.Lock()

def camera_streamer(cam_name, config):
    source = config["source"]
    floor_id = config["floor_id"]
    print(f"📷 Stream starting: {cam_name} (Target: {floor_id})")
    cap = cv2.VideoCapture(source)
    previous_frame = None
    MOTION_THRESHOLD = 15000  

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(2)
            cap = cv2.VideoCapture(source)
            continue

        with frame_lock: latest_display_frames[cam_name] = frame.copy()

        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)
        if previous_frame is None:
            previous_frame = gray
            continue

        thresh = cv2.threshold(cv2.absdiff(previous_frame, gray), 25, 255, cv2.THRESH_BINARY)[1]
        motion_level = cv2.countNonZero(thresh)
        previous_frame = gray

        if motion_level > MOTION_THRESHOLD and not ai_processing_queue.full():
            ai_processing_queue.put((cam_name, floor_id, frame))

alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end", ocr_model="cct-xs-v2-global-model")

for name, cfg in CAMERA_CONFIGS.items():
    threading.Thread(target=camera_streamer, args=(name, cfg), daemon=True).start()

print("\n🚀 Multi-Camera Setup Active! Press ESC to stop.\n")

ACCUMULATION_WINDOW = 7.0
sessions = {name: {"active": False, "start": 0, "counter": Counter()} for name in CAMERA_CONFIGS}

while True:
    try:
        try:
            cam_name, floor_id, frame = ai_processing_queue.get_nowait()
            cv2.imwrite(f"/tmp/temp_{cam_name}.jpg", frame)
            results = alpr.predict(f"/tmp/temp_{cam_name}.jpg")
            
            valid_plates = []
            for r in results:
                if r.ocr and r.ocr.text:
                    p = re.sub(r'[^A-Z0-9]', '', r.ocr.text.strip().upper())
                    if is_valid_indian_plate(p): valid_plates.append(p)

            s = sessions[cam_name]
            if valid_plates:
                if not s["active"]:
                    s["active"], s["start"] = True, time.time()
                    s["counter"].clear()
                    print(f"\n⏱️ [{cam_name}] Motion & Plate detected! Scanning...")
                for p in valid_plates: s["counter"][p] += 1
        except queue.Empty:
            pass 

        now = time.time()
        for cam_name, s in sessions.items():
            if s["active"] and (now - s["start"]) >= ACCUMULATION_WINDOW:
                if s["counter"]:
                    merged = merge_fuzzy_reads(s["counter"], max_dist=1)
                    best_plate, count = merged.most_common(1)[0]
                    if count >= 2:
                        target_id = CAMERA_CONFIGS[cam_name]["floor_id"]
                        print(f"\n✅ [{cam_name}] Confirmed: {best_plate}")
                        server.log_vehicle_from_camera(best_plate, floor_id=target_id)
                    else:
                        print(f"\n❌ [{cam_name}] Rejected: '{best_plate}' (Seen {count}x).")
                s["active"] = False
                s["counter"].clear()
                print(f"⏳ [{cam_name}] Resetting motion gate...\n")

        with frame_lock: display_copies = list(latest_display_frames.items())
        for win, img in display_copies: cv2.imshow(f"Live: {win}", img)
        if cv2.waitKey(1) & 0xFF == 27: break

    except KeyboardInterrupt: break

cv2.destroyAllWindows()