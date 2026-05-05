"""Seed script — populates DB with 10 technicians, their service areas, specialties,
and two weeks of availability slots. Idempotent: skips if technicians already exist."""
import asyncio
from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import AsyncSessionLocal
from database.models import (
    ApplianceType, AvailabilitySlot, ServiceArea, Specialty, Technician,
)

TECHNICIANS = [
    {
        "name": "Marcus Johnson",
        "email": "marcus.johnson@searshome.com",
        "phone": "312-555-0101",
        "zip_codes": ["20121", "60605", "60610"],
        "specialties": [ApplianceType.WASHER, ApplianceType.DRYER, ApplianceType.DISHWASHER],
    },
    {
        "name": "Sarah Chen",
        "email": "sarah.chen@searshome.com",
        "phone": "312-555-0102",
        "zip_codes": ["60614", "60622", "60610"],
        "specialties": [ApplianceType.REFRIGERATOR, ApplianceType.FREEZER],
    },
    {
        "name": "Emily Thompson",
        "email": "emily.thompson@searshome.com",
        "phone": "312-555-0104",
        "zip_codes": ["60601", "60657", "60605"],
        "specialties": [ApplianceType.OVEN, ApplianceType.MICROWAVE],
    },
    {
        "name": "James Williams",
        "email": "james.williams@searshome.com",
        "phone": "312-555-0105",
        "zip_codes": ["60640", "60657", "60660"],
        "specialties": [ApplianceType.WASHER, ApplianceType.DRYER],
    },
    {
        "name": "Lisa Martinez",
        "email": "lisa.martinez@searshome.com",
        "phone": "312-555-0106",
        "zip_codes": ["60605", "60614", "60622"],
        "specialties": [ApplianceType.REFRIGERATOR, ApplianceType.DISHWASHER],
    },
    {
        "name": "Robert Kim",
        "email": "robert.kim@searshome.com",
        "phone": "312-555-0107",
        "zip_codes": ["60622", "60630", "60640"],
        "specialties": [ApplianceType.REFRIGERATOR],
    },
    {
        "name": "Jennifer Brown",
        "email": "jennifer.brown@searshome.com",
        "phone": "312-555-0108",
        "zip_codes": ["60601", "60610", "60614"],
        "specialties": [ApplianceType.WASHER, ApplianceType.DRYER, ApplianceType.OVEN],
    },
    {
        "name": "Michael Davis",
        "email": "michael.davis@searshome.com",
        "phone": "312-555-0109",
        "zip_codes": ["60640", "60660", "60626"],
        "specialties": [ApplianceType.DISHWASHER, ApplianceType.MICROWAVE],
    },
    {
        "name": "Patricia Garcia",
        "email": "patricia.garcia@searshome.com",
        "phone": "312-555-0110",
        "zip_codes": ["60657", "60626", "60660"],
        "specialties": list(ApplianceType),  # handles all appliance types
    },
]

# Morning (8–12), afternoon (12–17), evening (17–20) slots
SLOT_WINDOWS = [
    (time(8, 0), time(12, 0)),
    (time(12, 0), time(17, 0)),
    (time(17, 0), time(20, 0)),
]


async def seed(session: AsyncSession) -> None:
    existing = await session.scalar(select(func.count()).select_from(Technician))
    if existing:
        print(f"Seed skipped — {existing} technicians already in database.")
        return

    today = date.today()

    for tech_data in TECHNICIANS:
        tech = Technician(
            name=tech_data["name"],
            email=tech_data["email"],
            phone=tech_data["phone"],
        )
        session.add(tech)
        await session.flush()  # get tech.id

        for zip_code in tech_data["zip_codes"]:
            session.add(ServiceArea(technician_id=tech.id, zip_code=zip_code))

        for appliance in tech_data["specialties"]:
            session.add(Specialty(technician_id=tech.id, appliance_type=appliance))

        # Two weeks of availability — skip Sundays, alternate slot windows
        for day_offset in range(1, 15):
            slot_date = today + timedelta(days=day_offset)
            if slot_date.weekday() == 6:  # Sunday
                continue
            # Each tech gets 2 of the 3 windows per day (staggered by tech index)
            tech_idx = TECHNICIANS.index(tech_data)
            windows = SLOT_WINDOWS[tech_idx % 2 : tech_idx % 2 + 2]
            for start, end in windows:
                session.add(AvailabilitySlot(
                    technician_id=tech.id,
                    date=slot_date,
                    start_time=start,
                    end_time=end,
                    is_booked=False,
                ))

    await session.commit()
    print("Database seeded successfully.")


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await seed(session)


if __name__ == "__main__":
    asyncio.run(main())
