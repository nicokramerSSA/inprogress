"""Database connection and table definitions for FlowScope Miner.

Tables are created automatically on startup if they do not exist.
The raw uploaded file bytes are stored in the logs table so that
parsed DataFrames can be reconstructed after a server restart.
"""

import os
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    Column,
    DateTime,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()

projects = Table(
    "projects",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("name", String(255), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

logs = Table(
    "logs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("project_id", UUID(as_uuid=True), nullable=True),
    Column("filename", String(255), nullable=False),
    Column("file_data", LargeBinary, nullable=False),
    Column("file_format", String(10), nullable=False),
    Column("column_mapping", JSONB),
    Column("informational_columns", JSONB),
    Column("filter_only_columns", JSONB),
    Column("filter_only_values", JSONB),
    Column("mapping_warnings", JSONB),
    Column("uploaded_at", DateTime(timezone=True), server_default=func.now()),
)


def create_tables() -> None:
    """Create all tables if they do not already exist."""
    metadata.create_all(engine)
