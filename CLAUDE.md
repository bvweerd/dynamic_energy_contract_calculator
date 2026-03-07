# Dynamic Energy Contract Calculator
Home Assistant custom integration (HACS) that calculates electricity and gas costs using dynamic pricing sensors. Domain: `dynamic_energy_contract_calculator`, version tracked in `manifest.json` and `setup.cfg`.

## Commands
- Tests: `python -m pytest tests/ -v`
- Run single test: `python -m pytest tests/test_sensor.py -v`
- Lint: `ruff check custom_components/`
- Format: `ruff format custom_components/`
- Type check: `python -m mypy --strict custom_components/dynamic_energy_contract_calculator`
- Install deps: `pip install -r requirements.txt`
- Pre-commit: `pre-commit run --all-files`

## Structure
- `custom_components/dynamic_energy_contract_calculator/` — integration code
  - `__init__.py` — setup, config entry load/unload
  - `config_flow.py` — UI setup and options flow
  - `sensor.py` — energy/cost/profit sensors
  - `binary_sensor.py` — solar_bonus_active, production_price_positive
  - `entity.py` — base entity with state restoration
  - `const.py` — constants, price keys, supplier presets
  - `netting.py` — Dutch saldering (netting) logic
  - `solar_bonus.py` — zonnebonus calculation
  - `services.py` — reset_all_meters, reset_selected_meters, set_meter_value
  - `repair.py` — HA repair issues
  - `diagnostics.py` — HA diagnostics redaction
- `tests/` — pytest tests mirroring integration structure
- `manifest.json` — domain, version, codeowners
- `hacs.json` — HACS metadata

## HA conventions
- Use `async def` for all platform setup and I/O
- `_LOGGER = logging.getLogger(__name__)` in each module
- Type hints required on all public functions (mypy strict)
- Config entries via `config_flow.py` using `config_entries.ConfigFlow`
- Keep `version` in sync: `manifest.json` and `setup.cfg [bumpversion]`

## Test conventions
- Framework: `pytest-homeassistant-custom-component`
- Use `hass` fixture for HomeAssistant instance
- Snapshot tests via `syrupy` — update with `--snapshot-update`
- Config: `asyncio_mode=auto`, `--maxfail=1`, coverage on `custom_components`

## Compaction: always preserve
- List of modified files
- Test error messages and assertion details
- Current domain name and version
- Active branch
