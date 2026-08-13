from fastapi import HTTPException, status

from app.models.enums import DealStage, RoleEnum
from app.models.user import User

# Stage-aware rule: reps move deals through the pipeline freely, but closing a
# deal (won/lost) is an admin-only transition.
ADMIN_ONLY_STAGES = {DealStage.won, DealStage.lost}


def assert_can_set_stage(user: User, stage: DealStage) -> None:
    if stage in ADMIN_ONLY_STAGES and user.role is not RoleEnum.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Only an admin can move a deal to '{stage.value}'",
        )


def assert_can_access(user: User, owner_id: int) -> None:
    if user.role is not RoleEnum.admin and owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your record")
