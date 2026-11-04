"""Local development credentials only; replace with real identity before deployment."""
from dataclasses import dataclass
from secrets import compare_digest

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    role: str
    subject: str


def development_identity(
    request: Request,
    credential: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Identity:
    config = request.app.state.settings
    owner = config.dev_owner_credential
    agent = config.dev_agent_credential
    owner_key = owner.get_secret_value() if owner else ""
    agent_key = agent.get_secret_value() if agent else ""
    # Both must be configured and distinct. Never infer a role from request data.
    if not owner_key.strip() or not agent_key.strip() or compare_digest(owner_key.encode(), agent_key.encode()):
        raise HTTPException(503, "Development authentication is not configured")
    if credential is None:
        raise HTTPException(401, "Bearer credential required", headers={"WWW-Authenticate": "Bearer"})
    supplied = credential.credentials.encode()
    if compare_digest(supplied, owner_key.encode()):
        return Identity("owner", config.dev_owner_id)
    if compare_digest(supplied, agent_key.encode()):
        return Identity("agent", config.dev_agent_id)
    raise HTTPException(401, "Invalid credential", headers={"WWW-Authenticate": "Bearer"})


def owner_identity(identity: Identity = Depends(development_identity)) -> Identity:
    if identity.role != "owner":
        raise HTTPException(403, "Owner credential required")
    return identity


def agent_identity(identity: Identity = Depends(development_identity)) -> Identity:
    if identity.role != "agent":
        raise HTTPException(403, "Agent credential required")
    return identity
