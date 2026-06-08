from pydantic import BaseModel, Field

class MaterialLayer(BaseModel):
    name: str = Field(min_length=1)
    thickness_m: float = Field(gt=0)
    thermal_conductivity_w_mk: float = Field(gt=0)

class UValueInput(BaseModel):
    layers: list[MaterialLayer] = Field(min_length=1)
    rsi_m2k_w: float = Field(default=0.13, ge=0)
    rse_m2k_w: float = Field(default=0.04, ge=0)

class LayerResult(BaseModel):
    name: str
    thickness_m: float
    thermal_conductivity_w_mk: float
    r_value_m2k_w: float

class WarningMessage(BaseModel):
    level: str
    message: str

class UValueResults(BaseModel):
    layers: list[LayerResult]
    r_total_m2k_w: float
    u_value_w_m2k: float

class UValueResponse(BaseModel):
    calculator_id: str
    version: str
    status: str
    results: UValueResults
    warnings: list[WarningMessage]
    assumptions: list[str]
    limitations: list[str]
