"""FastAPI shared dependencies: Identity, Pool, Rate limiting.
Governing spec: BE-01 §9, BE-12 §3.1, BE-14.
"""

import uuid
from typing import Optional
from fastapi import Header, Depends
import asyncpg
from app.db.pool import get_pool
from app.core.config import Settings, get_settings
from app.core.errors import InvalidTokenError


class Identity:
    def __init__(self, owner_key: Optional[str], is_authenticated: bool = False):
        self.owner_key = owner_key
        self.is_authenticated = is_authenticated

    @property
    def is_anonymous(self) -> bool:
        return self.owner_key is None


async def get_identity(
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    settings: Settings = Depends(get_settings),
) -> Identity:
    """Resolve caller identity. Bearer token wins over session ID (BE-12-R7)."""
    # 1. Bearer Token
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        # For authenticated users, token decoding will resolve user:<sub>
        # Minimal verification placeholder for phase 1 / mock
        try:
            # Simple check or mock token extraction
            return Identity(owner_key=f"user:{token[:36]}", is_authenticated=True)
        except Exception:
            raise InvalidTokenError()

    # 2. Session ID (UUIDv4 validation per BE-12-R9)
    if x_session_id:
        try:
            val = uuid.UUID(x_session_id)
            return Identity(owner_key=f"session:{str(val)}", is_authenticated=False)
        except ValueError:
            pass

    # 3. Anonymous without owner key (BE-12-R8)
    return Identity(owner_key=None, is_authenticated=False)
