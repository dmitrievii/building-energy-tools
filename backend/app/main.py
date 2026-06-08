from fastapi import FastAPI

from app.api.calculators import router as calculators_router

app = FastAPI(title="Building Energy Tools API", version="0.1.0")
app.include_router(calculators_router, prefix="/api/calculators", tags=["calculators"])

@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
