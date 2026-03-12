"""Add tool_call_id column to messages table.

Stores the LLM-assigned tool_call_id so multi-turn conversations
can correctly link tool results to their parent assistant tool_calls.

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("tool_call_id", sa.String(64), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("messages", "tool_call_id")
