import os
from improv_parking_database import DB_PATH, initialize_database

print("⚠️ Preparing to reset database...")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"🗑️ Successfully deleted old database: {DB_PATH}")
else:
    print(f"ℹ️ No existing database found at {DB_PATH}.")

initialize_database()
print("✅ Database has been completely reset and is ready to use!")