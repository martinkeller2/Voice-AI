"""Initial schema — technicians, scheduling, and appointments

Revision ID: 001
Revises:
Create Date: 2026-05-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APPLIANCE_VALUES = (
    "washer", "dryer", "refrigerator", "dishwasher", "oven",
     "microwave", "freezer",
)

# checkfirst=True makes create/drop idempotent — safe on retries
_appliance_enum = postgresql.ENUM(*_APPLIANCE_VALUES, name="appliancetype")

# Used inside create_table — create_type=False tells SQLAlchemy
# the type already exists and not to issue a second CREATE TYPE
_appliance_col = lambda: sa.Column(  # noqa: E731
    "appliance_type",
    postgresql.ENUM(*_APPLIANCE_VALUES, name="appliancetype", create_type=False),
    nullable=True,
)


def upgrade() -> None:
    bind = op.get_bind()

    # Create enum only if it doesn't already exist (safe on retries)
    _appliance_enum.create(bind, checkfirst=True)

    op.create_table(
        "technicians",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_technicians_id", "technicians", ["id"])
    op.create_index("ix_technicians_email", "technicians", ["email"], unique=True)

    op.create_table(
        "service_areas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "technician_id",
            sa.Integer(),
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("zip_code", sa.String(10), nullable=False),
        sa.UniqueConstraint("technician_id", "zip_code", name="uq_service_areas_tech_zip"),
    )
    op.create_index("ix_service_areas_id", "service_areas", ["id"])
    op.create_index("ix_service_areas_zip_code", "service_areas", ["zip_code"])

    op.create_table(
        "specialties",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "technician_id",
            sa.Integer(),
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _appliance_col(),
        sa.UniqueConstraint(
            "technician_id", "appliance_type", name="uq_specialties_tech_appliance"
        ),
    )
    op.create_index("ix_specialties_id", "specialties", ["id"])

    op.create_table(
        "availability_slots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "technician_id",
            sa.Integer(),
            sa.ForeignKey("technicians.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_booked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_availability_slots_id", "availability_slots", ["id"])

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "technician_id",
            sa.Integer(),
            sa.ForeignKey("technicians.id"),
            nullable=False,
        ),
        sa.Column(
            "slot_id",
            sa.Integer(),
            sa.ForeignKey("availability_slots.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("customer_name", sa.String(100), nullable=False),
        sa.Column("customer_phone", sa.String(20), nullable=True),
        sa.Column("customer_zip", sa.String(10), nullable=True),
        _appliance_col(),
        sa.Column("issue_description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_appointments_id", "appointments", ["id"])


def downgrade() -> None:
    op.drop_table("appointments")
    op.drop_table("availability_slots")
    op.drop_table("specialties")
    op.drop_table("service_areas")
    op.drop_table("technicians")
    _appliance_enum.drop(op.get_bind(), checkfirst=True)
