from flask import request, session
from extensions import db
from models import AuditLog


def audit(action, entity_type, entity_id=None, before=None, after=None):
    log = AuditLog(
        user_id=session.get("user_id"), action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before_json=before, after_json=after,
        ip_address=(request.headers.get("X-Forwarded-For", request.remote_addr) or "")[:64],
    )
    db.session.add(log)
