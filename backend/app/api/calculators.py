from fastapi import APIRouter

from calculators.u_value.schema import UValueInput, UValueResponse
from calculators.u_value.model import calculate_u_value

router = APIRouter()

@router.post("/u-value", response_model=UValueResponse)
def u_value_calculator(data: UValueInput) -> UValueResponse:
    return calculate_u_value(data)
