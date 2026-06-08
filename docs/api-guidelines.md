# API Guidelines

## API principle
Frontend forms send JSON to FastAPI endpoints. FastAPI validates inputs, calls Python calculator modules, and returns structured JSON.

## Common endpoint pattern
```text
POST /api/calculators/{calculator_id}
```

## Common response format
```json
{
  "calculator_id": "u_value",
  "version": "0.1.0",
  "status": "success",
  "results": {},
  "warnings": [],
  "assumptions": [],
  "limitations": []
}
```
