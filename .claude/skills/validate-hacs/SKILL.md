---
name: validate-hacs
description: Validate the HACS integration for compliance
---

# Validate HACS

1. Check `manifest.json`: domain, name, version, requirements, dependencies, codeowners
2. Check `hacs.json`: name, render_readme, zip_release, filename
3. Verify `version` is in sync between `manifest.json` and `setup.cfg [bumpversion]`
4. Check file structure: `custom_components/dynamic_energy_contract_calculator/__init__.py` present
5. Check for `README.md` at root
6. Verify no runtime dependencies that aren't in `manifest.json` requirements
7. Report issues and suggest fixes
