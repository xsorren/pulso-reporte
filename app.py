from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from financial_calculations import compute_financials

APP_API_KEY = os.getenv("APP_API_KEY")  # optional simple auth

app = FastAPI(title="Pulso Vital - Financial Calculations Service", version="1.0.0")


class ComputeRequest(BaseModel):
    datos_crudos: Dict[str, Any] | str = Field(..., description="Objeto datos_crudos (personal/ocupacional/economico/patrimonial/etc.)")
    flags: Dict[str, Any] = Field(default_factory=dict, description="Flags opcionales para anti-doble-conteo y normalización")


class ComputeResponse(BaseModel):
    raw: Dict[str, Any]
    formatted: Dict[str, Any]
    notes: list[str] = Field(default_factory=list)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/compute", response_model=ComputeResponse)
def compute(payload: ComputeRequest, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    datos_crudos_normalizado = payload.datos_crudos
    if isinstance(datos_crudos_normalizado, str):
        try:
            datos_crudos_normalizado = json.loads(datos_crudos_normalizado)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="datos_crudos inválido: JSON malformado")

    if not isinstance(datos_crudos_normalizado, dict) or not datos_crudos_normalizado:
        raise HTTPException(status_code=400, detail="datos_crudos requerido")

    raw, formatted, notes = compute_financials(datos_crudos_normalizado, payload.flags or {})
    return {"raw": raw, "formatted": formatted, "notes": notes}
