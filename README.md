# Dynamic Energy Contract Calculator

This Home Assistant custom integration adds utility sensors that calculate electricity or gas costs using current pricing information. It can track consumption or production and provides several helpers to manage the sensors.

![Example summary sensors](assets/readme/example_summary_sensors.png)

## Installation

1. **Via [HACS](https://hacs.xyz/):**
   - Add this repository as a custom integration in HACS.
   - Install **Dynamic Energy Contract Calculator** from the HACS list of integrations.
   - Restart Home Assistant to load the integration.

2. **Manual installation:**
   - Copy the `dynamic_energy_contract_calculator` folder from `custom_components` into your Home Assistant `custom_components` directory.
   - Restart Home Assistant.

## Configuration

1. In Home Assistant navigate to **Settings → Devices & Services** and use **Add Integration**.
2. Search for **Dynamic Energy Contract Calculator** and follow the setup flow.
3. Select the energy sensors you want to track and provide optional price sensors for live pricing.
   Values from multiple price sensors are added together, allowing you to keep separate sensors
   for things like dynamic tariff surcharges.
4. Optionally configure price settings such as markup and tax values.

Price settings can be changed later from the integration's options flow. See
the *Price Settings* section below for all available keys.

### Installation parameters

During setup you will be asked for the following information:

1. **Source type** – choose whether the selected sensors measure electricity
   consumption, electricity production or gas consumption.
2. **Energy sensors** – one or more sensors with the `energy` or `gas` device
   class that provide cumulative readings.
3. **Price sensors** – optional sensors or input_number entities that provide components of the current energy price
   in €/kWh, EUR/kWh, €/m³, or EUR/m³. You can select more than one; their values are summed.
   This makes it possible to add sensors that expose dynamic tariff surcharges or use manual input helpers for fixed tariffs.
4. **Price settings** – values from the table below used to calculate the final
   price.

See the [Home Assistant configuration documentation](https://www.home-assistant.io/docs/configuration/integrations/) for general details on adding custom integrations.

## Provided Sensors

For each configured source the integration creates the following sensors:

- `..._kwh_total` – total energy used/produced in kWh
- `..._cost_total` – accumulated cost in euro
- `..._profit_total` – accumulated profit in euro
- `..._kwh_during_cost_total` – kWh measured when the price is positive
- `..._kwh_during_profit_total` – kWh measured when the price is negative

In addition a few summary sensors are created:

- `sensor.electricity_contract_fixed_costs_total`
- `sensor.gas_contract_fixed_costs_total`
- `sensor.net_energy_cost_total`
- `sensor.energy_contract_cost_total`
- `sensor.current_consumption_price`
- `sensor.current_production_price`
- `sensor.current_gas_consumption_price`
- `sensor.solar_bonus_total` (when solar bonus is enabled)
- `binary_sensor.solar_bonus_active` (when solar bonus is enabled)
- `binary_sensor.production_price_positive` (when production is configured)

These sensors can be used in the [Energy dashboard](https://www.home-assistant.io/docs/energy/) or in your own automations.

### Solar Bonus Feature

When enabled, the integration automatically calculates solar bonus (zonnebonus) for electricity production. This feature:
- Tracks production during daylight hours (sunrise to sunset based on Home Assistant's sun entity)
- Applies a configurable bonus percentage (default 10%)
- Respects annual kWh limits (default 7,500 kWh)
- Only applies when production compensation is positive
- Automatically resets on contract anniversary (when contract start date is configured)
- Falls back to calendar year reset if no contract start date is set
- Uses exact sunrise/sunset times, which may result in fractional hour/quarter-hour periods in price data

**Contract Anniversary Reset:**
- Configure `contract_start_date` (format: YYYY-MM-DD) to track limits from your contract start date
- Enable `reset_on_contract_anniversary` to automatically reset all meters on the anniversary
- The annual kWh limit is calculated from the contract start date, not the calendar year
- Example: Contract starting 2024-07-01 will track limits from July 1 to June 30 each year

The `sensor.solar_bonus_total` shows the total bonus earned this contract year and has attributes for:
- `year_production_kwh`: Total eligible production this contract year
- `total_bonus_euro`: Total bonus amount earned

**Binary Sensors:**

The integration provides binary sensors for automation:

- `binary_sensor.solar_bonus_active` - On when solar bonus is currently being applied (daylight hours, positive price, under annual limit)
- `binary_sensor.production_price_positive` - On when the production compensation price is positive (useful for controlling inverters to zero export when prices are negative)

## Services

The integration exposes several services under the `dynamic_energy_contract_calculator` domain:

- `reset_all_meters` – reset all dynamic energy sensors to `0`
- `reset_selected_meters` – reset only the specified sensors
- `set_meter_value` – manually set the value of a sensor


Each service is documented in Home Assistant once the integration is installed. See the [service documentation](https://www.home-assistant.io/docs/scripts/service-calls/) for details on calling services.

## Supported Devices / Functions

The integration works with any energy or gas sensor that provides cumulative kWh or m³ readings. A price sensor is optional but allows for true dynamic pricing. Available services are:

- `reset_all_meters`
- `reset_selected_meters`
- `set_meter_value`

## Usage

Add the created sensors to your dashboards or use them in automations to keep
track of real-time energy costs. The integration provides several services (see
the *Services* section below) that can be called from automations or scripts to
reset meters or manually set a value.

## Use Cases

- Monitor day-to-day electricity and gas costs in the Energy dashboard.
- Compare consumption and production prices to determine when selling back to the grid is profitable.
- Combine the summary sensors in automations to keep track of monthly spending or trigger notifications when costs rise above a threshold.

## Examples

### Notify when daily cost exceeds €5

```yaml
alias: "Notify high daily cost"
trigger:
  - platform: numeric_state
    entity_id: sensor.energy_contract_cost_total
    above: 5
action:
  - service: notify.mobile_app_phone
    data:
      message: "Your energy usage exceeded €5 today."
```

### Reset all meters on the first day of the month

```yaml
alias: "Monthly meter reset"
trigger:
  - platform: time
    at: "00:00:00"
condition:
  - condition: template
    value_template: "{{ now().day == 1 }}"
action:
  - service: dynamic_energy_contract_calculator.reset_all_meters
```

## Price Settings

During configuration you can adjust several price related options. These values
are split into costs per kWh/m³ or per day and are further divided by
government, grid operator and supplier charges. All values are added on top of
the base price from your price sensor before VAT is calculated.

| Setting | Description |
| ------- | ----------- |
| `per_unit_supplier_electricity_markup` | Additional cost per kWh for electricity consumption. |
| `per_unit_supplier_electricity_production_markup` | Additional revenue per kWh for produced electricity. |
| `per_unit_government_electricity_tax` | Government tax per kWh for consumption. |
| `per_day_grid_operator_electricity_connection_fee` | Daily electricity network fees. |
| `per_day_supplier_electricity_standing_charge` | Fixed daily cost charged by your supplier. |
| `per_day_government_electricity_tax_rebate` | Daily rebate applied to reduce fixed costs. |
| `per_unit_supplier_gas_markup` | Additional cost per cubic meter of gas. |
| `per_unit_government_gas_tax` | Government tax per cubic meter of gas. |
| `per_day_grid_operator_gas_connection_fee` | Daily gas connection fees. |
| `per_day_supplier_gas_standing_charge` | Fixed daily gas contract cost. |
| `vat_percentage` | VAT rate that should be applied to all calculated prices. |
| `production_price_include_vat` | Whether to apply VAT to production compensation (default: False for Dutch private solar). |
| `average_prices_to_hourly` | Average quarter-hour prices to hourly (default: True). |
| `solar_bonus_enabled` | Enable solar bonus calculation for production. |
| `solar_bonus_percentage` | Bonus percentage applied to production (default 10%). |
| `solar_bonus_annual_kwh_limit` | Annual kWh limit for solar bonus (default 7500). |
| `contract_start_date` | Contract start date in YYYY-MM-DD format for anniversary tracking. |
| `reset_on_contract_anniversary` | Automatically reset all meters on contract anniversary. |

If your price sensors already provide prices **including** VAT, set
`vat_percentage` to `0` to avoid double counting.

### Configuration parameters

All of the parameters above can be changed later from the integration's options
flow. You can also modify the list of energy sensors or change the selected
price sensor at any time via **Settings → Devices & Services**.

## How Calculations Work

For every update of an energy sensor the integration calculates the change
since the previous update. This delta is multiplied by a price that depends on
the selected source type and the configured price settings.

### Consumption

Electricity consumption uses the formula:

```
price = (
    base_price
    + per_unit_supplier_electricity_markup
    + per_unit_government_electricity_tax
) * (1 + vat_percentage / 100)
```

Gas consumption uses:

```
price = (
    base_price
    + per_unit_supplier_gas_markup
    + per_unit_government_gas_tax
) * (1 + vat_percentage / 100)
```

### Production

For production sensors the supplier markup is added (since it's compensation, not cost). Depending on the
`production_price_include_vat` option VAT may or may not be applied:

```
if production_price_include_vat:
    price = (
        base_price
        + per_unit_supplier_electricity_production_markup
    ) * (1 + vat_percentage / 100)
else:
    price = base_price + per_unit_supplier_electricity_production_markup
```

**Note:** In the Netherlands, private solar panel owners receive production compensation that already includes VAT by law.
Therefore, `production_price_include_vat` should typically be set to `False` to avoid double-counting VAT.

The resulting price is multiplied by the energy delta (kWh or m³) and added to
the appropriate cost or profit sensor.

### Daily costs

Once per day at midnight fixed contract costs are added:

```
electricity_daily = (
    per_day_grid_operator_electricity_connection_fee
    + per_day_supplier_electricity_standing_charge
    - per_day_government_electricity_tax_rebate
) * (1 + vat_percentage / 100)

gas_daily = (
    per_day_grid_operator_gas_connection_fee
    + per_day_supplier_gas_standing_charge
) * (1 + vat_percentage / 100)
```

## Data Update

Dynamic sensors update whenever the linked energy sensor or price sensor changes. The integration listens for state changes, so updates happen immediately without polling. Daily cost sensors add their values at midnight using Home Assistant's scheduler.

## Troubleshooting

- **No sensors created:** check the Home Assistant logs for setup errors and
  verify that your energy sensors are selected during configuration.
- **Prices remain at 0:** ensure a valid price sensor is configured or manually
  set one in the options flow.
- **Resetting values:** use the `reset_all_meters` or `reset_selected_meters`
  services if the readings get out of sync.
- **Sensors unavailable:** if a sensor shows `unavailable`, verify the source and price sensors still report valid numeric values.
- **Negative totals:** make sure production sensors are configured with the correct source type so that profits and costs are calculated properly.

## VAT and feed‑in

Most energy suppliers display prices including 21&nbsp;% VAT. By default the
integration assumes prices *excluding* VAT and adds the configured VAT
percentage. If your price sensor already provides a price that includes VAT,
set `vat_percentage` to `0`.

Private solar panel owners do not need to pay VAT on electricity fed back to the
grid. The supplier includes VAT in the compensation you receive. To track your
income you can therefore use the same settings as for consumption: make sure the
entered tariff matches the amount you receive from the supplier (with or without
VAT) and adjust `vat_percentage` accordingly.

## Known Limitations

- Optional support for the Dutch netting (saldering) scheme. When enabled, the integration nets the energy tax (including VAT) against feed‑in before calculating the remaining costs.
- The integration relies on cumulative energy sensors. If a sensor resets unexpectedly the calculated totals may become inaccurate.
- Prices are taken from your own sensor; the integration does not fetch tariffs from suppliers.

## Example configuration

Below are screenshots from a typical installation that show the most important
steps of the setup flow. 

### 1. Start the configuration flow

![Main menu](assets/readme/main_menu.png)

The **Add integration** dialog lists *Dynamic Energy Contract Calculator*. After
selecting it you will be guided through a short setup wizard.

### 2. Choose which sensors to track

![Select sources](assets/readme/select_sources.png)

Here you select the energy sensors that should be monitored. You can choose
consumption, production or gas sensors. Optionally select a price sensor that
provides the current tariff.

### 3. Configure price settings

![Price settings](assets/readme/price_settings.png)

This screen lets you configure markups, surcharges and VAT. The values are added
on top of the base price reported by your price sensor.

The example above is based on a ANWB Dynamic Contract, with Enexis as grid operator and tax settings according to 2026 with gas consumption <500m3 per year and electricity <10.000kWh per year.

## Supplier Presets

The integration includes preset configurations for common energy suppliers. These presets can be manually applied or used as a reference.

### Zonneplan 2026

For Zonneplan contracts (2026 tariffs), use the `PRESET_ZONNEPLAN_2026` configuration available in `const.py`. This preset includes:

**Consumption costs (from Zonneplan contract, inclusive VAT):**
- Inkoopvergoeding: €0.02 per kWh
- Energiebelasting: €0.13165 per kWh
- Vaste leveringskosten: €6.25 per maand
- Netbeheerkosten: €39.48 per maand
- Vermindering energiebelasting: -€52.62 per maand

**Configuration values (exclusive VAT - integration calculates VAT):**
- Inkoopvergoeding: €0.01653 per kWh (€0.02 / 1.21)
- Energiebelasting: €0.10880 per kWh (€0.13165 / 1.21)
- Vaste leveringskosten: €0.17355 per dag (€6.25/30.42 / 1.21)
- Netbeheerkosten: €1.07438 per dag (€39.48/30.42 / 1.21)
- Vermindering energiebelasting: €1.42975 per dag (€52.62/30.42 / 1.21)

**Production revenue:**
- Vaste terugleververgoeding: €0.02 per kWh (exclusive VAT - no VAT on production compensation)
- Salderingsregeling: enabled (until 2027)

**Solar bonus (zonnebonus):**
- **Automatically calculated** when enabled (10% of base price + production markup)
- Only applied between sunrise and sunset based on official measurements (De Bilt, NL)
- Limited to first 7,500 kWh per contract year
- Only when (base_price + production_markup) is positive
- Automatically resets on contract anniversary when configured

**How Zonneplan calculates the solar bonus:**

Zonneplan calculates the solar bonus for electricity you return between sunrise and sunset. The calculation is based on quarter-hour readings from your smart meter, matching the exact moments of sunrise and sunset as closely as the meter's technical capabilities allow.

There is no fixed rounding to a standard quarter-hour before or after sunrise/sunset. Your return is registered per quarter-hour; as soon as there is solar production in a quarter after sunrise, it counts toward the bonus. The same applies around sunset: only until the last full quarter during daylight do you receive the bonus.

Although Zonneplan uses dynamic hourly prices, both registration and settlement occur based on these underlying quarter-hour data. You receive exactly what you're entitled to for each relevant consumption or return moment within an hour—without rounding beyond what is technically measurable.

**Important timing notes:**
- The integration uses the sun.sun entity from Home Assistant to determine sunrise and sunset times
- This means solar bonus periods start and end at the exact sunrise/sunset times, not at fixed hour boundaries
- When hourly price averaging is enabled (`average_prices_to_hourly: true`), hours containing sunrise or sunset may show different effective start/end times in the price attributes
- The quarter-hour or hourly return rates in attributes will reflect partial-hour solar bonus periods during sunrise and sunset hours

**Contract management:**
- Set `contract_start_date` to your actual contract start date for accurate year tracking
- Enable `reset_on_contract_anniversary` to automatically reset all meters yearly
- Leave `contract_start_date` empty to use calendar year tracking

**Important notes:**
- All configuration values are **exclusive of VAT** (integration adds 21% VAT)
- EPEX Day Ahead sensors typically provide prices exclusive of VAT
- The integration calculates the final price: (EPEX + markup + tax) × 1.21
- Production compensation already includes VAT per Dutch law for private solar owners
- Powerplay feed-in has separate compensation rules not covered by this preset

**Price calculation example:**
```
EPEX price: €0.10/kWh (exclusive VAT)
+ Inkoopvergoeding: €0.01653/kWh
+ Energiebelasting: €0.10880/kWh
= €0.22533/kWh (subtotal exclusive VAT)
× 1.21 (VAT)
= €0.27265/kWh (final price inclusive VAT)
```

**Manual configuration:**

To apply these settings manually during setup or via the options flow:

```yaml
# All values EXCLUSIVE of VAT - integration will add 21% VAT for consumption
per_unit_supplier_electricity_markup: 0.01653  # €0.02 incl. VAT / 1.21
per_unit_supplier_electricity_production_markup: 0.02  # €0.02 excl. VAT (no VAT on production)
per_unit_government_electricity_tax: 0.10880  # €0.13165 incl. VAT / 1.21
per_day_grid_operator_electricity_connection_fee: 1.07438  # €39.48/month / 30.42 / 1.21
per_day_supplier_electricity_standing_charge: 0.17355  # €6.25/month / 30.42 / 1.21
per_day_government_electricity_tax_rebate: 1.42975  # €52.62/month / 30.42 / 1.21
vat_percentage: 21.0  # Integration calculates VAT
production_price_include_vat: false  # No VAT on production compensation
netting_enabled: true
average_prices_to_hourly: true  # Zonneplan uses hourly averages
solar_bonus_enabled: true
solar_bonus_percentage: 10.0
solar_bonus_annual_kwh_limit: 7500.0
contract_start_date: "2024-01-01"  # Set your actual contract start date
reset_on_contract_anniversary: true
```

**Price sensor setup:**

For Zonneplan you'll need an EPEX Day Ahead price sensor. You can use integrations like:
- [EPEX Spot](https://github.com/TheFes/epex-spot-sensor) custom integration
- [Nordpool](https://github.com/custom-components/nordpool) (includes EPEX data)

More information about Zonneplan tariffs: [www.zonneplan.nl/energie](https://www.zonneplan.nl/energie)

### Greenchoice Gas 2026

For Greenchoice gas contracts (2026 tariffs), use the `PRESET_GREENCHOICE_GAS_2026` configuration. This is a gas-only preset for the "Aardgas met Natuur voor Morgen" fixed contract.

**Configuration values (exclusive VAT):**
- Leveringstarief: €0.39020 per m³ (€0.47214 incl. VAT / 1.21)
- Energiebelasting: €0.57816 per m³ (€0.69957 incl. VAT / 1.21)
- Netbeheerkosten: €0.58740 per dag (€0.71075 incl. VAT / 1.21)
- Vaste leveringskosten: €0.22249 per dag (€0.26922 incl. VAT / 1.21)

**Manual configuration:**

```yaml
per_unit_supplier_gas_markup: 0.39020
per_unit_government_gas_tax: 0.57816
per_day_grid_operator_gas_connection_fee: 0.58740
per_day_supplier_gas_standing_charge: 0.22249
vat_percentage: 21.0
```

### 4. Resulting sensors

![Example production sensor](assets/readme/example_production_sensor.png)

![Example summary sensors](assets/readme/example_summary_sensors.png)

After finishing the wizard the integration creates individual sensors for each
source as well as summary sensors that combine the totals.

## Removal

To remove the integration open **Settings → Devices & Services**, locate
**Dynamic Energy Contract Calculator**, choose **Delete** from the menu and
confirm. All created sensors will be removed from Home Assistant.
