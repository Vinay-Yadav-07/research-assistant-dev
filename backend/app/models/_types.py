"""Column helpers shared by the models."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from sqlalchemy import DateTime, Uuid, func, text
from sqlalchemy.orm import mapped_column

# Must equal the embedding model's dimension (EMBEDDING_DIMENSION); changing it needs a new
# migration and re-indexing (D-013, D-050). A unit test keeps it equal to the settings default.
EMBEDDING_DIMENSION = 384


def one_of(column: str, values: tuple[str, ...]) -> str:
    """SQL for a CHECK that `column` holds one of `values`."""
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


UUIDPrimaryKey = Annotated[
    UUID, mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
]
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    ),
]
