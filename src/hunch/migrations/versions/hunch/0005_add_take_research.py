"""add take research and link revisions to it

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01 15:00:00.000000

Research and portfolio construction are independent steps (ADR 0008). Every research of a take's
target universe is its own row (``hunch__take_research``: brief, candidates with roles and
conviction, rationale, evidence, the model that answered, the recorded requests), numbered per
take. A basket revision records the research it was constructed from (``research_uid``, nullable
for the revisions built before this revision; set to null when the research row goes).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REVISION_RESEARCH_FK = "fk__hunch__take_revision__research_uid__hunch__take_bea8fef478"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hunch__take_research",
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("take_uid", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("brief_json", sa.JSON(), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=False),
        sa.Column("rationale_md", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("inference_request_uids", sa.JSON(), nullable=True),
        sa.Column("conversation_uid", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["take_uid"],
            ["hunch__take.uid"],
            name=op.f("fk__hunch__take_research__take_uid__hunch__take__uid"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__hunch__take_research")),
        info={
            "namespace": "hunch",
            "identifier": "hunch.HunchTakeResearch",
            "markets_storage_app": "hunch",
        },
    )
    op.create_index(
        op.f("uix__hunch__take_research__take_uid__number"),
        "hunch__take_research",
        ["take_uid", "number"],
        unique=True,
    )

    with op.batch_alter_table("hunch__take_revision", schema=None) as batch_op:
        batch_op.add_column(sa.Column("research_uid", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            op.f(_REVISION_RESEARCH_FK),
            "hunch__take_research",
            ["research_uid"],
            ["uid"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("hunch__take_revision", schema=None) as batch_op:
        batch_op.drop_constraint(op.f(_REVISION_RESEARCH_FK), type_="foreignkey")
        batch_op.drop_column("research_uid")

    op.drop_index(
        op.f("uix__hunch__take_research__take_uid__number"), table_name="hunch__take_research"
    )
    op.drop_table("hunch__take_research")
