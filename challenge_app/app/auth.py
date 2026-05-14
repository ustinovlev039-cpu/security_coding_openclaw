from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class User:
    username: str
    role: str
    can_execute_commands: bool


USERS_BY_TOKEN = {
    "owner-token": User(
        username="training_owner",
        role="owner",
        can_execute_commands=True,
    ),
    "operator-token": User(
        username="training_operator",
        role="operator",
        can_execute_commands=True,
    ),
    "viewer-token": User(
        username="training_viewer",
        role="viewer",
        can_execute_commands=False,
    ),
}


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    token = credentials.credentials.strip()
    user = USERS_BY_TOKEN.get(token)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return user