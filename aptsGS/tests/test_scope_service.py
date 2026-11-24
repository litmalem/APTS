from app.scope_service import ScopeMatcher


def test_cidr_scope_match():
    matcher = ScopeMatcher()
    result = matcher.target_in_scope(
        "127.0.0.1",
        [
            {
                "scope_target_id": "t1",
                "target_type": "CIDR",
                "target_value": "127.0.0.0/8",
                "allowed": 1,
            }
        ],
    )
    assert result.matched is True


def test_out_of_scope_is_rejected():
    matcher = ScopeMatcher()
    result = matcher.target_in_scope(
        "10.10.10.10",
        [
            {
                "scope_target_id": "t1",
                "target_type": "CIDR",
                "target_value": "127.0.0.0/8",
                "allowed": 1,
            }
        ],
    )
    assert result.matched is False


def test_source_allowlist():
    matcher = ScopeMatcher()
    result = matcher.source_allowed(
        "nvd-cve",
        [{"scope_source_id": "s1", "source_id": "nvd-cve", "allowed": 1}],
    )
    assert result.matched is True
