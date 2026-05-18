from fastapi import HTTPException, status

from app.auth import User


def require_command_access(user: User) -> None:
    """ Обычная команда достпуны owner and operator. """
    if not user.can_execute_commands:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Command access required",
        )

def require_owner(user: User) -> None:
    """ Owner-only зоны доступны только owner. """
    if user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required",
        )