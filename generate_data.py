import sqlite3
import random
from datetime import datetime, timedelta

DB_NAME = "parking.db"

conn = sqlite3.connect(DB_NAME)
cursor = conn.cursor()

vehicles = [
    "PB10AB1234",
    "HR26XY5678",
    "DL05PQ2222",
    "CH01AA9999",
    "UP32MN8888",
    "RJ14CD4567",
    "HP12XY9087",
    "JK01LM2345",
    "UK07PQ6789",
    "HR98AA0000"
]

floors = ["B1", "B2", "GF"]

today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

print("Generating dummy parking history...")

for plate in vehicles:

    entry = today + timedelta(
        minutes=random.randint(0, 480)
    )

    duration = random.randint(30, 240)

    exit_time = entry + timedelta(
        minutes=duration
    )

    floor = random.choice(floors)

    cursor.execute("""
        INSERT INTO parking_history
        (plate_number, entry_time, exit_time, duration_minutes)
        VALUES (?, ?, ?, ?)
    """, (
        plate,
        entry.strftime("%Y-%m-%d %H:%M:%S"),
        exit_time.strftime("%Y-%m-%d %H:%M:%S"),
        duration
    ))

print("Generating active vehicles...")

active = [
    "PB08XX1111",
    "DL09YY2222",
    "HR07ZZ3333"
]

for plate in active:

    entry = today + timedelta(
        minutes=random.randint(0, 500)
    )

    cursor.execute("""
        INSERT OR REPLACE INTO active_parking
        (plate_number, entry_time)
        VALUES (?, ?)
    """, (
        plate,
        entry.strftime("%Y-%m-%d %H:%M:%S")
    ))

conn.commit()
conn.close()

print("Dummy data inserted successfully!")