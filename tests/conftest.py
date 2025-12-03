import os
import time

import pytest


@pytest.fixture(autouse=True)
async def set_time_zone(hass):
    """Set a valid IANA time zone for Home Assistant tests.

    Using Europe/Amsterdam to match the UTC+2 timestamps in tests.
    """
    os.environ["TZ"] = "Europe/Amsterdam"
    if hasattr(time, "tzset"):
        time.tzset()
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    # Set location to Amsterdam, Netherlands
    hass.config.latitude = 52.3676
    hass.config.longitude = 4.9041
    yield
