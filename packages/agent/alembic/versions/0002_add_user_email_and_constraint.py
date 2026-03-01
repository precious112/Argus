"""Add email column to users and replace global unique with composite.

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(255), server_default=""))
    op.drop_constraint("users_username_key", "users")
    op.create_unique_constraint("uq_user_tenant_username", "users", ["tenant_id", "username"])
    op.create_index("ix_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_index("ix_users_email", "users")
    op.drop_constraint("uq_user_tenant_username", "users")
    op.create_unique_constraint("users_username_key", "users", ["username"])
    op.drop_column("users", "email")
