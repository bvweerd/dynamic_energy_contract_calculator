import pytest
from homeassistant.core import HomeAssistant
from custom_components.dynamic_energy_contract_calculator.repair import (
    async_report_issue,
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
