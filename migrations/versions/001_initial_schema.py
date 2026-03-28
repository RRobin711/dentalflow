"""Initial schema — patients, claims, eligibility_checks.

Revision ID: 001
Revises: None
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "patients",
        sa.Column("id", sa.dialects.postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("date_of_birth", sa.Date, nullable=False),
        sa.Column("insurance_provider", sa.String(100), nullable=False),
        sa.Column("insurance_id", sa.String(100), nullable=False),
        sa.Column("plan_type", sa.String(10), nullable=False),
        sa.Column("annual_maximum_cents", sa.Integer, nullable=False, server_default="150000"),
        sa.Column("annual_used_cents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("plan_type IN ('PPO', 'HMO', 'DHMO')", name="ck_patients_plan_type"),
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.dialects.postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        # No FK to patients — validated via API call to patient service (microservices decoupling)
        sa.Column("patient_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("cdt_code", sa.String(10), nullable=False),
        sa.Column("cdt_description", sa.String(200)),
        sa.Column("procedure_date", sa.Date, nullable=False),
        sa.Column("tooth_number", sa.Integer),
        sa.Column("charged_amount_cents", sa.Integer, nullable=False),
        sa.Column("has_xray", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_narrative", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_perio_chart", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.String(30), nullable=False, server_default="created"),
        sa.Column("denial_risk_score", sa.Float),
        sa.Column("denial_risk_factors", sa.dialects.postgresql.JSONB),
        sa.Column("scored_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('created','queued','scoring','scored','submitted','accepted','denied','error')",
            name="ck_claims_status",
        ),
    )
    op.create_index("idx_claims_status", "claims", ["status"])
    op.create_index("idx_claims_patient_id", "claims", ["patient_id"])
    op.create_index("idx_claims_idempotency_key", "claims", ["idempotency_key"])

    op.create_table(
        "eligibility_checks",
        sa.Column("id", sa.dialects.postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("patient_id", sa.dialects.postgresql.UUID(), nullable=False),
        sa.Column("insurance_provider", sa.String(100), nullable=False),
        sa.Column("cdt_code", sa.String(10), nullable=False),
        sa.Column("coverage_percent", sa.Integer),
        sa.Column("eligible", sa.Boolean, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], name="fk_eligibility_patient"),
    )


def downgrade() -> None:
    op.drop_table("eligibility_checks")
    op.drop_table("claims")
    op.drop_table("patients")
