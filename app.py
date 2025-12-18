from __future__ import annotations

import os
import json
import ast
import urllib.parse
from typing import Any, Dict, Optional, Tuple, List

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from financial_calculations import compute_financials

APP_API_KEY = os.getenv("APP_API_KEY")  # optional simple auth

app = FastAPI(title="Pulso Vital - Financial Calculations Service", version="1.0.0")


class ComputeRequest(BaseModel):
    datos_crudos: Dict[str, Any] | str = Field(
        ...,
        description="Objeto datos_crudos (personal/ocupacional/economico/patrimonial/etc.)",
    )
    flags: Dict[str, Any] = Field(
        default_factory=dict,
        description="Flags opcionales para anti-doble-conteo y normalización",
    )


class ComputeResponse(BaseModel):
    raw: Dict[str, Any]
    formatted: Dict[str, Any]
    notes: list[str] = Field(default_factory=list)


@app.get("/health")
def health():
    return {"ok": True}


def _parse_request_payload(text: str) -> Any:
    """
    Intenta parsear el body tolerando varios formatos típicos cuando Bubble/API Connector
    envía algo que no es JSON puro:
    - JSON normal: {"a":1}
    - JSON dentro de string: "{\"a\":1}"
    - form-urlencoded: body=%7B%22a%22%3A1%7D
    - dict estilo Python con comillas simples: {'a': 1}
    """
    t = (text or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail={"error": "Empty body"})

    # 1) JSON normal
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # 2) form-urlencoded tipo "body=...."
    if t.startswith("body="):
        try:
            decoded = urllib.parse.unquote_plus(t[5:])
            return json.loads(decoded)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid JSON (body=...)", "preview": t[:400]},
            )

    # 3) dict estilo Python (comillas simples) u otras variantes parseables
    try:
        return ast.literal_eval(t)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid JSON", "preview": t[:400]},
        )


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    """
    Normaliza el payload para garantizar que sea dict:
    - Si viene como string, intenta json.loads.
    - Si no es dict al final, lanza 422.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail={"error": "Body es string pero no JSON parseable", "preview": payload[:400]},
            )

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Body debe ser un objeto JSON con datos_crudos y flags")

    return payload


def _normalize_datos_crudos(datos_crudos: Any) -> Dict[str, Any]:
    """
    datos_crudos puede venir como dict o como string JSON.
    """
    if isinstance(datos_crudos, str):
        try:
            datos_crudos = json.loads(datos_crudos)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="datos_crudos inválido: JSON malformado")

    if not isinstance(datos_crudos, dict) or not datos_crudos:
        raise HTTPException(status_code=400, detail="datos_crudos requerido")

    return datos_crudos


@app.post("/compute", response_model=ComputeResponse)
async def compute(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Leer body crudo (evita 500 cuando request.json() falla)
    raw_bytes = await request.body()
    text = raw_bytes.decode("utf-8", errors="replace")

    # Log útil en Render para diagnosticar Bubble (sin spamear todo el body)
    print("---- /compute raw body preview ----")
    print(text.strip()[:400])
    print("---- end preview ----")

    # Parse tolerante
    payload_any = _parse_request_payload(text)
    payload = _normalize_payload(payload_any)

    datos_crudos = _normalize_datos_crudos(payload.get("datos_crudos"))
    flags = payload.get("flags") or {}
    if not isinstance(flags, dict):
        # si viene raro, no rompemos; lo forzamos a dict vacío
        flags = {}

    raw, formatted, notes = compute_financials(datos_crudos, flags)
    return {"raw": raw, "formatted": formatted, "notes": notes}
