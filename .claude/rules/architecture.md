# Project Architecture

## Directory structure
```
custom_components/dynamic_energy_contract_calculator/
  __init__.py       — config entry setup/unload, coordinator init
  config_flow.py    — UI setup wizard and options flow
  sensor.py         — cost/profit/kWh sensors (per source + summaries)
  binary_sensor.py  — solar_bonus_active, production_price_positive, delivery_price_positive
  entity.py         — base entity with state restoration logic
  const.py          — all constants, config keys, supplier presets
  netting.py        — Dutch saldering (netting) calculation
  solar_bonus.py    — zonnebonus calculation (sunrise-to-sunset, annual limits)
  services.py       — reset_all_meters, reset_selected_meters, set_meter_value
  repair.py         — HA issue repair handlers
  diagnostics.py    — HA diagnostics with sensitive data redaction
  manifest.json     — domain, version, codeowners
tests/
  conftest.py       — shared fixtures
  test_sensor.py    — main sensor tests
  test_binary_sensor.py
  test_config_flow.py / test_options_flow.py
  test_services.py
  test_solar_bonus.py
  test_repair.py / test_diagnostics.py
  test_presets.py
  test_entity_edge_cases.py / test_sensor_additional.py / test_sensor_platform_setup.py
```

## Core components
- **entity.py** — `DynamicEnergyEntity` base with `RestoreSensor`; handles state persistence across HA restarts
- **sensor.py** — per-source sensors (cost, profit, kWh) + summary sensors (net cost, fixed costs, current prices)
- **config_flow.py** — multi-step setup: source type → energy sensors → price sensors → price settings
- **const.py** — `PRICE_KEYS`, source type enums, `PRESET_ZONNEPLAN_2026`, `PRESET_GREENCHOICE_GAS_2026`
- **netting.py / solar_bonus.py** — standalone calculation modules, no HA dependencies

## External dependencies
- `pytest-homeassistant-custom-component` — HA test harness (provides `hass` fixture)
- `syrupy` — snapshot testing for sensor states/attributes
- No runtime dependencies beyond Home Assistant itself (`requirements: []` in manifest)
