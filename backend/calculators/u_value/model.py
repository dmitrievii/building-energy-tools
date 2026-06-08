from calculators.u_value.schema import LayerResult, UValueInput, UValueResponse, UValueResults, WarningMessage

CALCULATOR_ID = "u_value"
VERSION = "0.1.0"

def calculate_u_value(data: UValueInput) -> UValueResponse:
    layer_results = []
    for layer in data.layers:
        r_value = layer.thickness_m / layer.thermal_conductivity_w_mk
        layer_results.append(LayerResult(name=layer.name, thickness_m=layer.thickness_m, thermal_conductivity_w_mk=layer.thermal_conductivity_w_mk, r_value_m2k_w=r_value))

    r_layers = sum(layer.r_value_m2k_w for layer in layer_results)
    r_total = data.rsi_m2k_w + r_layers + data.rse_m2k_w
    u_value = 1 / r_total

    warnings = []
    if u_value > 0.5:
        warnings.append(WarningMessage(level="warning", message="U-value is relatively high for many external envelope applications."))

    return UValueResponse(
        calculator_id=CALCULATOR_ID,
        version=VERSION,
        status="success",
        results=UValueResults(layers=layer_results, r_total_m2k_w=r_total, u_value_w_m2k=u_value),
        warnings=warnings,
        assumptions=["One-dimensional steady-state heat transfer is assumed.", "Surface resistances are included as input parameters."],
        limitations=["Thermal bridges are not included.", "Moisture behaviour is not assessed.", "This calculation does not replace detailed building physics assessment."],
    )
