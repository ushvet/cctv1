"""
Hikvision AI CCTV Platform — Sample Data Seeder
Seeds the database with mock cameras, events, and test face/plate entries
for development and UI testing.

Usage: python scripts/seed_sample_data.py
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.db.session import async_session_factory, engine
from app.db.models import Camera, Event, LicensePlate, AlertLog


async def seed():
    """Populate database with realistic sample data."""
    async with async_session_factory() as session:
        print("🌱 Seeding sample data...")

        # -------------------------------------------------------
        # Sample Events (last 24 hours)
        # -------------------------------------------------------
        # Get cameras
        result = await session.execute(text("SELECT id, name FROM cameras LIMIT 10"))
        cameras = result.fetchall()

        if not cameras:
            print("⚠️  No cameras found. Run docker compose up first to initialize the DB.")
            return

        event_templates = [
            ("isapi_linedetection", "human", 0.85),
            ("isapi_linedetection", "vehicle", 0.78),
            ("isapi_fielddetection", "human", 0.92),
            ("frigate_detection", "person", 0.88),
            ("frigate_detection", "car", 0.82),
            ("frigate_detection", "motorcycle", 0.75),
            ("isapi_VMD", "unknown", 0.60),
            ("isapi_facedetection", "face", 0.90),
        ]

        now = datetime.now(timezone.utc)
        events_created = 0

        for i in range(50):
            cam = random.choice(cameras)
            template = random.choice(event_templates)
            hours_ago = random.uniform(0, 48)
            confidence = template[2] + random.uniform(-0.1, 0.1)

            event = Event(
                camera_id=cam[0],
                event_source=template[0],
                target_type=template[1],
                confidence=max(0.5, min(1.0, confidence)),
                timestamp=now - timedelta(hours=hours_ago),
                is_acknowledged=random.random() > 0.6,
                metadata_json={
                    "seeded": True,
                    "zones": random.choice([["entrance"], ["parking"], ["backyard"], []]),
                },
            )
            session.add(event)
            events_created += 1

        print(f"  ✅ Created {events_created} sample events")

        # -------------------------------------------------------
        # Sample License Plates
        # -------------------------------------------------------
        sample_plates = [
            ("MH12AB1234", "Rahul Sharma", "whitelist", "White Honda City"),
            ("MH14CD5678", "Priya Patel", "resident", "Black Toyota Innova"),
            ("KA01EF9012", "Unknown", "blacklist", "Red Maruti Swift"),
            ("DL03GH3456", "Security Vehicle", "whitelist", "Grey Tata Nexon"),
            ("GJ05IJ7890", "Delivery Partner", "registered", "Blue Ashok Leyland Truck"),
        ]

        plates_created = 0
        for plate_num, owner, category, desc in sample_plates:
            # Check if already exists
            existing = await session.execute(
                text("SELECT id FROM license_plates WHERE plate_number = :pn"),
                {"pn": plate_num},
            )
            if existing.fetchone():
                continue

            plate = LicensePlate(
                plate_number=plate_num,
                owner_name=owner,
                category=category,
                vehicle_description=desc,
            )
            session.add(plate)
            plates_created += 1

        print(f"  ✅ Created {plates_created} sample license plates")

        await session.commit()
        print("\n🎉 Database seeded successfully!")
        print("   Dashboard: http://localhost:8000")
        print("   API Docs:  http://localhost:8000/docs")


if __name__ == "__main__":
    asyncio.run(seed())
