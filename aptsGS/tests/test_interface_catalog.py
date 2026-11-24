from app.config import Settings
from app.interface_catalog import build_interface_catalog, cti_health_url


def test_interface_catalog_exposes_governance_and_dependencies():
    cfg = Settings(
        host="127.0.0.1",
        port=8770,
        db_host="127.0.0.1",
        db_port=3307,
        db_name="apts_governance",
        cti_event_api_url="http://127.0.0.1:8765/api/cti/events/publish",
    )

    catalog = build_interface_catalog(cfg)
    assert any(row["port"] == 8770 for row in catalog["provided"])
    assert any(row["provider"] == "MariaDB" and row["port"] == 3307 for row in catalog["consumed"])
    assert any(row["provider"] == "VulnDesk CTI Event API" and row["port"] == 8765 for row in catalog["consumed"])
    assert cti_health_url(cfg) == "http://127.0.0.1:8765/health"
