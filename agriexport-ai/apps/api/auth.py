"""Pilot Bearer-token RBAC. Only token hashes and tenant/role metadata are configured."""

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    actor_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    roles: set[str]


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    actor_id: str
    roles: frozenset[str]


def load_credentials() -> dict[str, Credential]:
    """No configured credentials means private endpoints fail closed."""
    raw = json.loads(os.getenv("AGRI_AUTH_CREDENTIALS", "{}"))
    credentials = {}
    for token_hash, record in raw.items():
        if len(token_hash) != 64 or any(c not in "0123456789abcdef" for c in token_hash):
            raise ValueError("Auth configuration keys must be lowercase SHA-256 token hashes")
        credential = Credential.model_validate(record)
        if not credential.roles or not credential.roles <= {"exporter", "analyst", "admin"}:
            raise ValueError("Unknown or missing role")
        credentials[token_hash] = credential
    return credentials


def require_roles(credentials: dict[str, Credential], allowed: set[str]):
    """Return an injected, tenant-bound identity; administrators never bypass tenant scope."""
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        request: Request, supplied: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
    ) -> Principal:
        if supplied is None:
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
            )
        digest = hashlib.sha256(supplied.credentials.encode()).hexdigest()
        record = next(
            (v for key, v in credentials.items() if hmac.compare_digest(key, digest)), None
        )
        if record is None:
            raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        principal = Principal(record.tenant_id, record.actor_id, frozenset(record.roles))
        request.state.principal = principal
        if not principal.roles & allowed:
            raise HTTPException(403, "Role does not permit this action")
        return principal

    return authenticate
