---
paths:
  - "custom_components/**/*.py"
---

# Code Style

## Formatting
- Formatter: `ruff format` (replaces black), line length 88
- Import sorter: `isort` with multi_line_output=3, trailing comma, line_length=88
- Import sections: FUTURE, STDLIB, INBETWEENS, THIRDPARTY, FIRSTPARTY, LOCALFOLDER
- known_first_party: `custom_components`, `tests`

## Linting
- Linter: `ruff check --fix` (replaces flake8)
- flake8 ignores: E501, W503, E203, D202, W504
- Also run: `pre-commit run --all-files` before committing

## Type hints
- **Required** on all public functions (mypy strict mode)
- mypy target: Python 3.13, `--strict --ignore-missing-imports`
- `--warn-unused-ignores`, `--warn-redundant-casts`, `--warn-unreachable`
- `--disallow-untyped-defs`, `--disallow-untyped-calls`
- No implicit optional

## HA-specific patterns
- Use `_LOGGER = logging.getLogger(__name__)` at module level
- All I/O in `async def` functions
- Entity classes inherit from HA entity hierarchy (e.g., `SensorEntity`, `BinarySensorEntity`)
- Config flow: inherit from `config_entries.ConfigFlow`
- Restore state via `RestoreEntity` / `RestoreSensor`
