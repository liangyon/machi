"""add_cauldron_mode_to_recommendation_sessions

Adds Cauldron (seed-based vibe-matching) support to recommendation_sessions:
  - mode: tracks whether a session was "standard" (profile-based) or
    "cauldron" (seed-based). Defaults to "standard" so all existing rows
    remain unaffected.
  - cauldron_seed_ids: JSON array of MAL IDs used as seeds for cauldron
    sessions. NULL for standard sessions.

Uses batch_alter_table for SQLite compatibility.

Revision ID: a3f7c2e8d1b5
Revises: f8a2e1d4c9b3
Create Date: 2026-03-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f7c2e8d1b5'
down_revision: Union[str, None] = 'f8a2e1d4c9b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recommendation_sessions") as batch_op:
        # "standard" = normal profile-based generation
        # "cauldron" = seed-based vibe-matching (no profile required)
        batch_op.add_column(
            sa.Column("mode", sa.String(20), nullable=False, server_default="standard")
        )
        # JSON array of seed MAL IDs (e.g. [21, 1735, 11061]).
        # NULL for standard sessions — only set for cauldron sessions.
        batch_op.add_column(
            sa.Column("cauldron_seed_ids", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendation_sessions") as batch_op:
        batch_op.drop_column("cauldron_seed_ids")
        batch_op.drop_column("mode")
