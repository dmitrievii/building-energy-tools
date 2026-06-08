from pydantic import BaseModel, Field

class DegreeDaysInput(BaseModel):
    daily_mean_temperatures_c: list[float] = Field(min_length=1)
    heating_base_temperature_c: float = 18.0
    cooling_base_temperature_c: float = 22.0

class DegreeDaysResults(BaseModel):
    heating_degree_days_kd: float
    cooling_degree_days_kd: float
    heating_days: int
    cooling_days: int

class DegreeDaysResponse(BaseModel):
    calculator_id: str
    version: str
    status: str
    results: DegreeDaysResults
    warnings: list[str]
    assumptions: list[str]
    limitations: list[str]
