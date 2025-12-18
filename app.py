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


from fastapi import FastAPI, Header, HTTPException, Request
import json
from typing import Any, Dict, Optional

@app.post("/compute")
async def compute(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload: Any = await request.json()

    # Si Bubble manda el body como STRING: "\"{...}\""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Body inválido: JSON malformado")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Body debe ser un objeto JSON")

    datos_crudos = payload.get("datos_crudos")
    flags = payload.get("flags") or {}

    # Si datos_crudos viene como string, también lo soportamos:
    if isinstance(datos_crudos, str):
        try:
            datos_crudos = json.loads(datos_crudos)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="datos_crudos inválido: JSON malformado")

    if not isinstance(datos_crudos, dict) or not datos_crudos:
        raise HTTPException(status_code=400, detail="datos_crudos requerido")

    raw, formatted, notes = compute_financials(datos_crudos, flags)
    return {"raw": raw, "formatted": formatted, "notes": notes}

