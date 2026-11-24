"""Human console authorization, sharing the existing server-owned registry."""
from fastapi import Depends, HTTPException
from .approval_auth import ApprovalPrincipal, require_human_approver

PERMISSIONS = {
    'VIEWER': {'read'}, 'AUDITOR': {'read'},
    'OPERATOR': {'read', 'mission_author', 'emergency_activate', 'retry'},
    'SECURITY_APPROVER': {'read', 'approve'},
    'GOVERNANCE_ADMIN': {'read', 'mission_author', 'scope', 'policy', 'revoke', 'emergency_activate', 'emergency_release', 'retry'},
}

def capabilities(principal):
    result = set()
    for role in principal.roles:
        result.update(PERMISSIONS.get(role, set()))
    # Existing bespoke approval roles remain usable only on the original
    # approval endpoint, whose required role check is authoritative.
    return sorted(result)


def require(permission):
    def dependency(principal: ApprovalPrincipal = Depends(require_human_approver)):
        if permission not in capabilities(principal):
            raise HTTPException(403, 'CONSOLE_PERMISSION_REQUIRED: ' + permission)
        return principal
    return dependency
