"""Conservative accounting for a completed, sanitized bounded web collection."""
from adapters.profile_contract import validate_profile


def completed_request_cost(observation, reserved):
    """Unknown/legacy/invalid results retain their complete reservation."""
    try:
        validate_profile(observation)
        count = observation['scan_metrics']['requests_performed']
        if type(reserved) is int and 1 <= count <= reserved:
            return count
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    return reserved
