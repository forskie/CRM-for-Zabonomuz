from .models import AuditLog


def record_audit(user, action, target_type, target_id, description):
    """Append a single audit record. One INSERT, no related queries."""
    AuditLog.objects.create(actor=user, action=action, target_type=target_type, target_id=target_id, description=description)
