from calculators.u_value.model import calculate_u_value
from calculators.u_value.schema import MaterialLayer, UValueInput

def test_u_value_basic_case() -> None:
    data = UValueInput(layers=[MaterialLayer(name="Insulation", thickness_m=0.20, thermal_conductivity_w_mk=0.04)], rsi_m2k_w=0.13, rse_m2k_w=0.04)
    response = calculate_u_value(data)
    assert response.status == "success"
    assert round(response.results.r_total_m2k_w, 2) == 5.17
    assert round(response.results.u_value_w_m2k, 3) == 0.193
