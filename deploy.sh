#!/bin/bash
set -e

SRC="$(dirname "$0")/custom_components/dynamic_energy_contract_calculator"
DEST="/media/data/homeassistant/config/custom_components/dynamic_energy_contract_calculator"

echo "Deploying dynamic_energy_contract_calculator to HA..."
rsync -av --delete "$SRC/" "$DEST/"
echo "Done."
