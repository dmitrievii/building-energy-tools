from calculators.degree_days.schema import DegreeDaysInput, DegreeDaysResponse, DegreeDaysResults

CALCULATOR_ID = "degree_days"
VERSION = "0.1.0"

def calculate_degree_days(data: DegreeDaysInput) -> DegreeDaysResponse:
    hdd_values = [max(0.0, data.heating_base_temperature_c - temp) for temp in data.daily_mean_temperatures_c]
    cdd_values = [max(0.0, temp - data.cooling_base_temperature_c) for temp in data.daily_mean_temperatures_c]
    return DegreeDaysResponse(
        calculator_id=CALCULATOR_ID,
        version=VERSION,
        status="success",
        results=DegreeDaysResults(heating_degree_days_kd=sum(hdd_values), cooling_degree_days_kd=sum(cdd_values), heating_days=sum(1 for v in hdd_values if v > 0), cooling_days=sum(1 for v in cdd_values if v > 0)),
        warnings=[],
        assumptions=["Daily mean outdoor temperatures are used.", "Base temperatures are user-defined."],
        limitations=["Solar gains, internal gains, and thermal mass are not considered.", "This is a climate indicator, not a building energy simulation."],
    )
