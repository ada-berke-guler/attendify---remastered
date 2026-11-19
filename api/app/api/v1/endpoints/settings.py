from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.models import SystemConfig, User
from app.schemas.schemas import SystemConfigOut, SystemConfigUpdate

router = APIRouter()


def _get_or_create_config(user: User, db: Session) -> SystemConfig:
    config = db.query(SystemConfig).filter(SystemConfig.user_id == user.id).first()
    if not config:
        config = SystemConfig(user_id=user.id)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/system-config", response_model=SystemConfigOut, summary="My settings (absence threshold)")
def get_system_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SystemConfigOut:
    return SystemConfigOut.model_validate(_get_or_create_config(current_user, db))


@router.patch("/system-config", response_model=SystemConfigOut, summary="Update my settings")
def update_system_config(
    payload: SystemConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemConfigOut:
    config = _get_or_create_config(current_user, db)
    if payload.absence_threshold is not None:
        config.absence_threshold = payload.absence_threshold
    db.commit()
    db.refresh(config)
    return SystemConfigOut.model_validate(config)
