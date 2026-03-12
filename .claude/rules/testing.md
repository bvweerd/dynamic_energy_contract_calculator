---
paths:
  - "tests/**/*"
  - "test_*.py"
---

# Testing

## Framework
- `pytest` + `pytest-homeassistant-custom-component`
- Snapshot testing: `syrupy` — update snapshots with `--snapshot-update`
- asyncio_mode: `auto` (no need to decorate tests with `@pytest.mark.asyncio`)
- Config: `--maxfail=1 --disable-warnings -q --strict`
- Coverage: `--cov=custom_components`

## Running tests
- All: `python -m pytest tests/ -v`
- Single file: `python -m pytest tests/test_sensor.py -v`
- Update snapshots: `python -m pytest tests/ --snapshot-update`
- With coverage: `python -m pytest tests/ --cov=custom_components --cov-report=term-missing`

## Fixtures (from conftest.py)
- `hass` — HomeAssistant instance (from pytest-homeassistant-custom-component)
- Use `async_setup_component` or config entry helpers to load the integration
- Mock external state changes via `hass.states.async_set()`

## Conventions
- Test files mirror the integration: `tests/test_<module>.py`
- Use `async def test_*` for all test functions
- Mock HA state changes, not internal methods where possible
- Snapshot tests for sensor state/attributes use syrupy `.assert_match_snapshot()`
