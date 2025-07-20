# Dynamic Energy Calculator

This Home Assistant custom integration adds utility sensors that calculate electricity or gas costs using current pricing information. It can track consumption or production and provides several helpers to manage the sensors.

## Installation

1. **Via [HACS](https://hacs.xyz/):**
   - Add this repository as a custom integration in HACS.
   - Install **Dynamic Energy Calculator** from the HACS list of integrations.
   - Restart Home Assistant to load the integration.

2. **Manual installation:**
   - Copy the `dynamic_energy_calculator` folder from `custom_components` into your Home Assistant `custom_components` directory.
   - Restart Home Assistant.

## Configuration

1. In Home Assistant navigate to **Settings → Devices & Services** and use **Add Integration**.
2. Search for **Dynamic Energy Calculator** and follow the setup flow.
3. Select the energy sensors you want to track and provide an optional price sensor for live pricing.
4. Optionally configure price settings such as markup and tax values.

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

These sensors can be used in the [Energy dashboard](https://www.home-assistant.io/docs/energy/) or in your own automations.

## Services

The integration exposes several services under the `dynamic_energy_calculator` domain:

- `reset_all_meters` – reset all dynamic energy sensors to `0`
- `reset_selected_meters` – reset only the specified sensors
- `set_meter_value` – manually set the value of a sensor

Each service is documented in Home Assistant once the integration is installed. See the [service documentation](https://www.home-assistant.io/docs/scripts/service-calls/) for details on calling services.

## Usage

Add the created sensors to your dashboards or use them in automations to keep track of real-time energy costs. You can use the provided services to correct meter values or start new measurements when needed.

## Price Settings

During configuration you can adjust several price related options. These values
are added on top of the base price from your price sensor and are applied before
VAT is calculated.

| Setting | Description |
| ------- | ----------- |
| `electricity_consumption_markup_per_kwh` | Additional cost per kWh for electricity consumption. |
| `electricity_production_markup_per_kwh` | Additional revenue per kWh for produced electricity. |
| `electricity_surcharge_per_kwh` | Taxes or surcharges per kWh for consumption. |
| `electricity_surcharge_per_day` | Daily electricity surcharges. |
| `electricity_standing_charge_per_day` | Fixed daily cost charged by your supplier. |
| `electricity_tax_rebate_per_day` | Daily rebate applied to reduce fixed costs. |
| `gas_markup_per_m3` | Additional cost per cubic meter of gas. |
| `gas_surcharge_per_m3` | Taxes or surcharges per cubic meter of gas. |
| `gas_standing_charge_per_day` | Fixed daily gas contract cost. |
| `vat_percentage` | VAT rate that should be applied to all calculated prices. |

If your price sensors already provide prices **including** VAT, set
`vat_percentage` to `0` to avoid double counting.

## How Calculations Work

For every update of an energy sensor the integration calculates the consumed or
produced amount since the last update. The formula below is used to determine
the price per unit:

```
price = (base_price + markup + surcharge) * (1 + vat_percentage / 100)
```

- For production sensors the surcharge is not used.
- For gas sensors the per‑m³ values are used instead of per‑kWh.

The delta in energy (kWh or m³) is multiplied by this price and added to the
appropriate cost or profit sensor. Daily sensors add their values once per day
at midnight.

## BTW (VAT) en teruglevering

De meeste energieleveranciers tonen prijzen inclusief 21&nbsp;% BTW. De
integratie gaat standaard uit van prijzen *exclusief* BTW en telt het
opgegeven BTW-percentage er nog bij op. Wanneer jouw prijs-sensor al een
bedrag inclusief BTW doorgeeft, zet je `vat_percentage` dus op `0`.

Particuliere zonnepaneelbezitters hoeven zelf geen BTW af te dragen over de
teruggeleverde stroom. De leverancier verwerkt de BTW in de vergoeding die je
ontvangt. Voor het bijhouden van je opbrengst kun je daarom dezelfde instellingen
gebruiken zoals bij verbruik: zorg ervoor dat het ingevoerde tarief overeenkomt
met het bedrag dat je van de leverancier krijgt (al dan niet inclusief BTW) en
pas `vat_percentage` eventueel aan.

