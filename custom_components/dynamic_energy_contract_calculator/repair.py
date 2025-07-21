from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def async_report_issue(
    hass: HomeAssistant,
    issue_id: str,
    translation_key: str,
    placeholders: dict[str, str] | None = None,
) -> None:
    """Create a repair issue for this integration."""
    try:
        async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders=placeholders,
        )
    except Exception as err:  # pragma: no cover - issue registry may not be loaded
        _LOGGER.debug("Failed to create issue %s: %s", issue_id, err)


def async_clear_issue(hass: HomeAssistant, issue_id: str) -> None:
    """Delete a repair issue for this integration."""
    try:
        async_delete_issue(hass, DOMAIN, issue_id)
    except Exception as err:  # pragma: no cover - issue registry may not be loaded
        _LOGGER.debug("Failed to delete issue %s: %s", issue_id, err)
