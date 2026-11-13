"""Create demo campaigns, offer links and daily statistics."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(96), nullable=False, unique=True),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
    )
    op.create_table(
        "stream_offers",
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column("offer_id", sa.Integer(), primary_key=True),
        sa.Column("share", sa.Integer(), nullable=False),
    )
    op.create_table(
        "daily_stats",
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id"), primary_key=True),
        sa.Column("offer_id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.Column("conversions", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("daily_stats")
    op.drop_table("stream_offers")
    op.drop_table("campaigns")
