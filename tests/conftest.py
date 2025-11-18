import os
import time

import pytest


@pytest.fixture(autouse=True)
async def set_time_zone(hass):
    """Set a valid IANA time zone for Home Assistant tests."""
    os.environ["TZ"] = "America/Los_Angeles"
    if hasattr(time, "tzset"):
        time.tzset()
    hass.config.set_time_zone("America/Los_Angeles")
    yield
