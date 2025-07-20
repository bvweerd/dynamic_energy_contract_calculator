import pytest


@pytest.fixture(autouse=True)
async def set_time_zone(hass):
    """Set a valid IANA time zone for Home Assistant tests."""
    await hass.config.async_set_time_zone("America/Los_Angeles")
    yield
