"""Stage 6 execution and assurance plane, isolated from specialist agents.

Stage 6.1 defines and persists requests only. Authorization, dispatch, adapters,
target access, results and execution evidence require later Stage 6 controls.
"""

from .execution_contract import (
    EXECUTION_REQUEST_CONTROL_VERSION,
    EXECUTION_REQUEST_SCHEMA_VERSION,
    canonical_execution_request_contract,
    canonical_execution_request_definition,
    normalize_execution_request,
    seal_execution_request,
    verify_execution_request,
    verify_canonical_action_envelope,
)

