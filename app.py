from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from financial_calculations import compute_financials

APP_API_KEY = os.getenv("APP_API_KEY")  # optional simple auth

app = FastAPI(title="Pulso Vital - Financial Calculations Service", version="1.0.0")


class ComputeRequest(BaseModel):
    datos_crudos: Dict[str, Any] = Field(..., description="Objeto datos_crudos (personal/ocupacional/economico/patrimonial/etc.)")
    flags: Dict[str, Any] = Field(default_factory=dict, description="Flags opcionales para anti-doble-conteo y normalización")


class ComputeResponse(BaseModel):
    raw: Dict[str, Any]
    formatted: Dict[str, Any]
    notes: list[str] = []


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/compute", response_model=ComputeResponse)
def compute(payload: ComputeRequest, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    raw, formatted, notes = compute_financials(payload.datos_crudos, payload.flags or {})
    return {"raw": raw, "formatted": formatted, "notes": notes}
