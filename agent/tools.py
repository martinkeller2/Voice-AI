"""Tool schemas (Groq/OpenAI function-calling format) and async handler implementations."""
import json
from datetime import date

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    ApplianceType, Appointment, AvailabilitySlot, ServiceArea,
    Specialty, Technician,
)

# ---------------------------------------------------------------------------
# Tool schemas — Groq / OpenAI function-calling format
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_available_technicians",
            "description": (
                "Search for technicians who service the given zip code and specialize in the given "
                "appliance type. Returns a list of technicians with their next available time slots. "
                "Call this before booking to show the customer their options."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "zip_code": {
                        "type": "string",
                        "description": "Customer's 5-digit zip code.",
                    },
                    "appliance_type": {
                        "type": "string",
                        "enum": [a.value for a in ApplianceType],
                        "description": "The type of appliance that needs service.",
                    },
                },
                "required": ["zip_code", "appliance_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book a specific availability slot for a customer. "
                "You must call find_available_technicians first to get a valid slot_id. "
                "Returns confirmation details including technician name, date, and time window."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_id": {
                        "type": "integer",
                        "description": "The availability slot ID to book (from find_available_technicians).",
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Full name of the customer.",
                    },
                    "customer_phone": {
                        "type": "string",
                        "description": "Customer's callback phone number.",
                    },
                    "customer_zip": {
                        "type": "string",
                        "description": "Customer's zip code.",
                    },
                    "appliance_type": {
                        "type": "string",
                        "enum": [a.value for a in ApplianceType],
                        "description": "The appliance type being serviced.",
                    },
                    "issue_description": {
                        "type": "string",
                        "description": "Brief description of the reported issue.",
                    },
                },
                "required": ["slot_id", "customer_name", "customer_zip", "appliance_type"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------

async def find_available_technicians(
    zip_code: str,
    appliance_type: str,
    db: AsyncSession,
) -> dict:
    today = date.today()

    try:
        appliance_enum = ApplianceType(appliance_type)
    except ValueError:
        return {"error": f"Unknown appliance type: {appliance_type}"}

    # Technicians who serve the zip AND specialize in the appliance
    stmt = (
        select(Technician)
        .join(ServiceArea, ServiceArea.technician_id == Technician.id)
        .join(Specialty, Specialty.technician_id == Technician.id)
        .where(
            and_(
                ServiceArea.zip_code == zip_code,
                Specialty.appliance_type == appliance_enum,
            )
        )
        .options(selectinload(Technician.availability_slots))
        .distinct()
    )

    result = await db.execute(stmt)
    technicians = result.scalars().all()

    if not technicians:
        return {
            "found": False,
            "message": f"No technicians found for zip code {zip_code} and appliance type {appliance_type}.",
        }

    output = []
    for tech in technicians:
        open_slots = [
            s for s in tech.availability_slots
            if not s.is_booked and s.date >= today
        ]
        open_slots.sort(key=lambda s: (s.date, s.start_time))
        next_slots = open_slots[:3]  # show up to 3 upcoming slots

        output.append({
            "technician_id": tech.id,
            "technician_name": tech.name,
            "technician_phone": tech.phone,
            "available_slots": [
                {
                    "slot_id": s.id,
                    "date": s.date.strftime("%A, %B %d, %Y"),
                    "start_time": s.start_time.strftime("%I:%M %p"),
                    "end_time": s.end_time.strftime("%I:%M %p"),
                }
                for s in next_slots
            ],
        })

    return {"found": True, "technicians": output}


async def book_appointment(
    slot_id: int,
    customer_name: str,
    customer_zip: str,
    appliance_type: str,
    db: AsyncSession,
    customer_phone: str = "",
    issue_description: str = "",
) -> dict:
    try:
        appliance_enum = ApplianceType(appliance_type)
    except ValueError:
        return {"error": f"Unknown appliance type: {appliance_type}"}

    stmt = (
        select(AvailabilitySlot)
        .where(AvailabilitySlot.id == slot_id)
        .options(selectinload(AvailabilitySlot.technician))
    )
    result = await db.execute(stmt)
    slot = result.scalar_one_or_none()

    if slot is None:
        return {"error": "Slot not found."}
    if slot.is_booked:
        return {"error": "That time slot has already been booked. Please choose another."}

    slot.is_booked = True
    appointment = Appointment(
        technician_id=slot.technician_id,
        slot_id=slot.id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_zip=customer_zip,
        appliance_type=appliance_enum,
        issue_description=issue_description,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)

    return {
        "success": True,
        "appointment_id": appointment.id,
        "technician_name": slot.technician.name,
        "technician_phone": slot.technician.phone,
        "date": slot.date.strftime("%A, %B %d, %Y"),
        "time_window": f"{slot.start_time.strftime('%I:%M %p')} – {slot.end_time.strftime('%I:%M %p')}",
        "service_zip": customer_zip,
        "appliance": appliance_type,
    }


async def execute_tool(name: str, tool_input: dict, db: AsyncSession) -> str:
    """Dispatch a Groq tool call and return a JSON result string."""
    if name == "find_available_technicians":
        result = await find_available_technicians(
            zip_code=tool_input["zip_code"],
            appliance_type=tool_input["appliance_type"],
            db=db,
        )
    elif name == "book_appointment":
        result = await book_appointment(
            slot_id=tool_input["slot_id"],
            customer_name=tool_input["customer_name"],
            customer_zip=tool_input["customer_zip"],
            appliance_type=tool_input["appliance_type"],
            customer_phone=tool_input.get("customer_phone", ""),
            issue_description=tool_input.get("issue_description", ""),
            db=db,
        )
    else:
        result = {"error": f"Unknown tool: {name}"}

    return json.dumps(result)
