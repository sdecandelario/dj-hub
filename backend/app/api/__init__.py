"""HTTP API under /api. Each module is one router."""
from ..db import session_scope


def get_session():
    with session_scope() as session:
        yield session
