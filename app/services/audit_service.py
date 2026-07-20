from sqlalchemy.orm import Session
from app.models.models import AuditLog, AuditAction


def log_action(
    db: Session,
    action: AuditAction,
    entity_type: str,
    entity_id: int,
    user_id: int,
    before_data: dict = None,
    after_data: dict = None,
    description: str = None
):
    log = AuditLog(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        before_data=before_data,
        after_data=after_data,
        description=description
    )
    db.add(log)
    db.flush()
