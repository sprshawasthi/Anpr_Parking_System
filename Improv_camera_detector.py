import time
import cv2
import os
import threading
import re
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
        
    # Absolute fail-safe backup list
    return "AN|AP|AR|AS|BH|BR|CG|CH|DD|DL|DN|GA|GJ|HR|HP|JH|JK|KA|KL|LA|LD|MH|ML|MN|MP|MZ|NL|OD|OR|PB|PY|RJ|SK|TG|TN|TR|TS|UA|UK|UP|WB"

print("🔄 Fetching latest state codes from Wikipedia...")
state_codes = fetch_live_wiki_codes()
# ===== 1. REGEX VALIDATION (STRICT STATE CODES) =====
def is_valid_indian_plate(text):
    if len(text) < 8:
        return False
    patterns = [
# Standard Plates 
        r'^(' + state_codes + r')[0-9]{2}[A-Z]{0,3}[0-9]{4}$',
        # Temporary Plates
        r'^T(' + state_codes + r')[0-9]{2}[A-Z]{0,3}[0-9]{4}$',
        # Bharat Series (BH)
        r'^[0-9]{2}BH[0-9]{4}[A-Z]{1,3}$',
        # Diplomatic / Consular Corps
        r'^[0-9]{1,3}(CD|CC)[0-9]{1,4}$',
        # Military / Armed Forces
        r'^[0-9]{2}[A-Z][0-9]{4,6}[A-Z]$'
    ]
    
    for pattern in patterns:
        if re.match(pattern, text):
            return True
            
    return False


# ===== 2. FUZZY OCR CORRECTION (LEVENSHTEIN) =====
def levenshtein_distance(s1, s2):
    """Calculates the minimum edits needed to turn s1 into s2."""
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
    """Merges plates with minor OCR errors into the most frequent valid plate."""
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

# ===== ALPR SETUP =====

alpr = ALPR(
    detector_model="yolo-v9-t-384-license-plate-end2end",
    ocr_model="cct-xs-v2-global-model",
)

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("❌ Could not open webcam.")
    exit()


# ===== PLATE ACCUMULATION =====

plate_counter = Counter()
is_accumulating = False
accumulation_start_time = 0
ACCUMULATION_WINDOW = 7.0

print("🚗 ANPR System Started")
print("Press ESC to stop.\n")


# ===== MAIN LOOP =====

while True:
    ret, frame = cap.read()

    if not ret:
        print("❌ Failed to capture frame.")
        break

    cv2.imwrite("/tmp/temp_frame.jpg", frame)

    try:
        results = alpr.predict("/tmp/temp_frame.jpg")

        current_frame_plates = []

        for result in results:
            if result.ocr and result.ocr.text:
                
                raw_text = result.ocr.text.strip().upper()
                
                plate_text = re.sub(r'[^A-Z0-9]', '', raw_text)
                
                if plate_text and is_valid_indian_plate(plate_text):
                    current_frame_plates.append(plate_text)

        if current_frame_plates:

            if not is_accumulating:
                is_accumulating = True
                accumulation_start_time = time.time()
                plate_counter.clear()
                print("\n⏱️ Plate detected! Starting scan window...")

            for plate in current_frame_plates:
                plate_counter[plate] += 1

    except Exception as e:
        print(f"ALPR Error: {e}")

    if is_accumulating:
        elapsed = time.time() - accumulation_start_time

        if elapsed >= ACCUMULATION_WINDOW:
            if plate_counter:
                merged_counter = merge_fuzzy_reads(plate_counter, max_dist=1)
                
                best_plate, count = merged_counter.most_common(1)[0]
                
                if count >= 2:
                    print(f"\n✅ Confirmed Plate: {best_plate} (seen {count} times after fuzzy merge)")
                    handle_vehicle_event(best_plate)
                else:
                    print(f"\n❌ Rejected: '{best_plate}' was only seen {count} time(s).")

            is_accumulating = False
            plate_counter.clear()
            print("\n⏳ Waiting for next vehicle...\n")

    cv2.imshow("SJVN ANPR System", frame)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
