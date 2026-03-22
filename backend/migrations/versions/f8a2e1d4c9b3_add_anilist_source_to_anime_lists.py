"""add_anilist_source_to_anime_lists

Adds AniList support fields to the anime_lists table:
  - source: tracks which import source was most recently used (mal | anilist)
  - anilist_username: the AniList username if imported from AniList
  - mal_username: made nullable (AniList-only users have no MAL username)

Uses batch_alter_table for SQLite compatibility (SQLite cannot ALTER COLUMN
directly — batch mode recreates the table under the hood).

Revision ID: f8a2e1d4c9b3
Revises: c302cb587ee1
Create Date: 2026-03-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a2e1d4c9b3'
down_revision: Union[str, None] = 'c302cb587ee1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("anime_lists") as batch_op:
        # Make mal_username nullable (AniList-only users have no MAL username)
        batch_op.alter_column(
            "mal_username",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        # Track the import source (defaults to "mal" for existing rows)
        batch_op.add_column(
            sa.Column("source", sa.String(length=20), nullable=False, server_default="mal")
        )
        # AniList username (nullable — only set when AniList is imported)
        batch_op.add_column(
            sa.Column("anilist_username", sa.String(length=255), nullable=True)
        )
        batch_op.create_index("ix_anime_lists_anilist_username", ["anilist_username"])


def downgrade() -> None:
    with op.batch_alter_table("anime_lists") as batch_op:
        batch_op.drop_index("ix_anime_lists_anilist_username")
        batch_op.drop_column("anilist_username")
        batch_op.drop_column("source")
        batch_op.alter_column(
            "mal_username",
            existing_type=sa.String(length=255),
            nullable=False,
        )
