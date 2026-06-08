from pydantic import BaseModel, Field

class EnvelopeElement(BaseModel):
    name: str = Field(min_length=1)
    area_m2: float = Field(gt=0)
    u_value_w_m2k: float = Field(gt=0)

class HeatingLoadInput(BaseModel):
    room_area_m2: float = Field(gt=0)
    room_volume_m3: float = Field(gt=0)
    indoor_design_temperature_c: float
    outdoor_design_temperature_c: float
    air_change_rate_1_h: float = Field(ge=0)
    envelope_elements: list[EnvelopeElement] = Field(min_length=1)

class HeatingLoadResults(BaseModel):
    delta_t_k: float
    transmission_heat_loss_w: float
    ventilation_heat_loss_w: float
    total_heating_load_w: float
    specific_heating_load_w_m2: float

class HeatingLoadResponse(BaseModel):
    calculator_id: str
    version: str
    status: str
    results: HeatingLoadResults
    warnings: list[str]
    assumptions: list[str]
    limitations: list[str]
