import pytest
from homeassistant.core import HomeAssistant
from custom_components.dynamic_energy_contract_calculator.repair import (
    async_report_issue,
    async_clear_issue,
)


async def test_async_report_issue_exception_handled(hass: HomeAssistant):
    def raise_issue(*args, **kwargs):
        raise Exception("boom")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "homeassistant.helpers.issue_registry.async_create_issue",
            raise_issue,
        )
        # Should not raise even if create_issue fails
        async_report_issue(hass, "x", "y", {"a": "b"})


async def test_async_clear_issue_calls_delete(hass: HomeAssistant):
    """Test that async_clear_issue calls async_delete_issue."""
    called = {}

    def mock_delete(hass_arg, domain, issue_id):
        called["hass"] = hass_arg
        called["domain"] = domain
        called["issue_id"] = issue_id

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "custom_components.dynamic_energy_contract_calculator.repair.async_delete_issue",
            mock_delete,
        )
        async_clear_issue(hass, "test_issue")

    assert called["domain"] == "dynamic_energy_contract_calculator"
    assert called["issue_id"] == "test_issue"
