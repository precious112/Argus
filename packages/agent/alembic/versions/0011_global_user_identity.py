"""Global user identity — one User per person, TeamMember for org links.

Deduplicates User rows by email, remaps TeamMembers, updates constraints,
and replaces the RLS policy on users so that a user is visible to any org
they belong to via team_members.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-07
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _remap_email_dupes(table: str, column: str) -> str:
    """Generate SQL to remap a user-id column from email-duplicate users to the canonical one."""
    return f"""
        WITH canonical AS (
            SELECT DISTINCT ON (email) id AS keep_id, email
            FROM users
            WHERE email != '' AND email IS NOT NULL
            ORDER BY email, created_at ASC
        ),
        dupes AS (
            SELECT u.id AS dup_id, c.keep_id
            FROM users u
            JOIN canonical c ON c.email = u.email
            WHERE u.id != c.keep_id
        )
        UPDATE {table}
        SET {column} = d.keep_id
        FROM dupes d
        WHERE {table}.{column} = d.dup_id
    """


def _remap_username_dupes(table: str, column: str) -> str:
    """Generate SQL to remap a user-id column from username-duplicate users to the canonical one."""
    return f"""
        WITH canonical AS (
            SELECT DISTINCT ON (username) id AS keep_id, username
            FROM users
            ORDER BY username, created_at ASC
        ),
        dupes AS (
            SELECT u.id AS dup_id, c.keep_id
            FROM users u
            JOIN canonical c ON c.username = u.username
            WHERE u.id != c.keep_id
        )
        UPDATE {table}
        SET {column} = d.keep_id
        FROM dupes d
        WHERE {table}.{column} = d.dup_id
    """


# All (table, column) pairs that reference users.id
_USER_ID_REFS = [
    ("team_members", "user_id"),
    ("password_reset_tokens", "user_id"),
    ("email_verification_tokens", "user_id"),
    ("investigations", "assigned_to"),
    ("investigations", "assigned_by"),
    ("service_configs", "owner_user_id"),
    ("escalation_policies", "primary_contact_id"),
    ("escalation_policies", "backup_contact_id"),
    ("slack_installations", "installed_by"),
]


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Deduplicate users by email: for each email with multiple rows,
    #    keep the oldest (smallest created_at), remap all references,
    #    then delete the duplicate rows.
    # ------------------------------------------------------------------ #

    # Remap all tables that hold user IDs
    for table, column in _USER_ID_REFS:
        op.execute(_remap_email_dupes(table, column))

    # Remove duplicate team_members that now have the same (tenant_id, user_id)
    op.execute("""
        DELETE FROM team_members
        WHERE id NOT IN (
            SELECT MIN(id) FROM team_members
            GROUP BY tenant_id, user_id
        )
    """)

    # Delete duplicate user rows (by email)
    op.execute("""
        WITH canonical AS (
            SELECT DISTINCT ON (email) id AS keep_id, email
            FROM users
            WHERE email != '' AND email IS NOT NULL
            ORDER BY email, created_at ASC
        )
        DELETE FROM users
        WHERE email != '' AND email IS NOT NULL
          AND id NOT IN (SELECT keep_id FROM canonical)
    """)

    # ------------------------------------------------------------------ #
    # 1b. Deduplicate by username (keep oldest) — handles any remaining
    #     collisions after the email dedup pass.
    # ------------------------------------------------------------------ #
    for table, column in _USER_ID_REFS:
        op.execute(_remap_username_dupes(table, column))

    op.execute("""
        DELETE FROM team_members
        WHERE id NOT IN (
            SELECT MIN(id) FROM team_members
            GROUP BY tenant_id, user_id
        )
    """)

    op.execute("""
        WITH canonical AS (
            SELECT DISTINCT ON (username) id AS keep_id, username
            FROM users
            ORDER BY username, created_at ASC
        )
        DELETE FROM users
        WHERE id NOT IN (SELECT keep_id FROM canonical)
    """)

    # ------------------------------------------------------------------ #
    # 2. Update constraints: drop per-tenant unique, add global unique
    # ------------------------------------------------------------------ #
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_user_tenant_username")
    op.execute("ALTER TABLE users ADD CONSTRAINT uq_user_username UNIQUE (username)")

    # Email unique — skip empty strings
    op.execute("""
        CREATE UNIQUE INDEX uq_user_email ON users (email)
        WHERE email != '' AND email IS NOT NULL
    """)

    # ------------------------------------------------------------------ #
    # 3. Replace RLS policy on users table
    # ------------------------------------------------------------------ #
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")

    # Read: user visible if they are a team_member of the current org
    op.execute("""
        CREATE POLICY user_read ON users FOR SELECT
        USING (id IN (
            SELECT user_id FROM team_members
            WHERE tenant_id = current_setting('app.current_tenant', true)
        ))
    """)

    # Write policies: controlled by application logic, not RLS
    op.execute("""
        CREATE POLICY user_write ON users FOR INSERT
        WITH CHECK (true)
    """)

    op.execute("""
        CREATE POLICY user_modify ON users FOR UPDATE
        USING (true) WITH CHECK (true)
    """)

    op.execute("""
        CREATE POLICY user_delete ON users FOR DELETE
        USING (true)
    """)


def downgrade() -> None:
    # Restore original RLS policy
    op.execute("DROP POLICY IF EXISTS user_read ON users")
    op.execute("DROP POLICY IF EXISTS user_write ON users")
    op.execute("DROP POLICY IF EXISTS user_modify ON users")
    op.execute("DROP POLICY IF EXISTS user_delete ON users")
    op.execute(
        "CREATE POLICY tenant_isolation ON users "
        "USING (tenant_id = current_setting('app.current_tenant', true)) "
        "WITH CHECK (tenant_id = current_setting('app.current_tenant', true))"
    )

    # Restore constraints
    op.execute("DROP INDEX IF EXISTS uq_user_email")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_user_username")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT uq_user_tenant_username "
        "UNIQUE (tenant_id, username)"
    )
