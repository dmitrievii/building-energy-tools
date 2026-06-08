from calculators.heating_load.schema import HeatingLoadInput, HeatingLoadResponse, HeatingLoadResults

CALCULATOR_ID = "heating_load"
VERSION = "0.1.0"

def calculate_heating_load(data: HeatingLoadInput) -> HeatingLoadResponse:
    delta_t = data.indoor_design_temperature_c - data.outdoor_design_temperature_c
    transmission = sum(e.area_m2 * e.u_value_w_m2k * delta_t for e in data.envelope_elements)
    ventilation = 0.34 * data.air_change_rate_1_h * data.room_volume_m3 * delta_t
    total = transmission + ventilation
    specific = total / data.room_area_m2
    warnings = []
    if delta_t <= 0:
        warnings.append("Indoor design temperature is not higher than outdoor design temperature.")
    if specific > 100:
        warnings.append("Specific heating load is high. Check envelope performance and ventilation assumptions.")
    return HeatingLoadResponse(
        calculator_id=CALCULATOR_ID,
        version=VERSION,
        status="success",
        results=HeatingLoadResults(delta_t_k=delta_t, transmission_heat_loss_w=transmission, ventilation_heat_loss_w=ventilation, total_heating_load_w=total, specific_heating_load_w_m2=specific),
        warnings=warnings,
        assumptions=["Steady-state design condition is assumed.", "Ventilation heat loss is calculated using 0.34 Wh/(m³K)."],
        limitations=["Thermal bridges are not explicitly included.", "Heat-up load is not included.", "This is a preliminary calculation, not a full standard-compliant heating load design."],
    )
