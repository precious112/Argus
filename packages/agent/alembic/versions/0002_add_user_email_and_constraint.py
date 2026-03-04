"""Add email column to users and replace global unique with composite.

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-28

NOTE: These changes have been folded into 0001. This migration is now a no-op.
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
