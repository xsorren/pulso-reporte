from __future__ import annotations

import os
import json
import ast
import pickle
import urllib.parse
from typing import Any, Dict, Optional

import faiss
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request
from openai import OpenAI
from pydantic import BaseModel, Field

from financial_calculations import compute_financials

APP_API_KEY = os.getenv("APP_API_KEY")  # optional simple auth

# ── Cliente OpenAI ─────────────────────────────────────────────────────────
openai_client: OpenAI | None = None
_openai_key = os.getenv("OPENAI_API_KEY")
if _openai_key:
    openai_client = OpenAI(api_key=_openai_key)
else:
    print("⚠️  OPENAI_API_KEY no configurada. El endpoint /obtener-contexto no podrá generar embeddings.")

# ── Carga de la base de conocimientos FAISS ────────────────────────────────
INDEX_FILE = "base_conocimiento.index"
TEXTOS_FILE = "textos.pkl"
EMBEDDING_MODEL = "text-embedding-3-small"

try:
    faiss_index = faiss.read_index(INDEX_FILE)
    with open(TEXTOS_FILE, "rb") as _f:
        textos_chunks: list[str] = pickle.load(_f)
    print(f"✅ Base de conocimientos cargada: {faiss_index.ntotal} vectores, {len(textos_chunks)} fragmentos.")
except Exception as e:
    faiss_index = None
    textos_chunks = None
    print(f"⚠️  No se pudo cargar la base de conocimientos ({e}). El endpoint /obtener-contexto devolverá un aviso.")

app = FastAPI(title="Pulso Vital - Financial Calculations Service", version="1.0.0")


class ContextRequest(BaseModel):
    query: str = Field(..., description="Consulta para buscar en la base de conocimientos de productos de seguros")


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

    # ✅ clave para Bubble: un string con TODA la respuesta JSON (para guardar o pasar tal cual)
    # Esto evita depender de "raw body text" (que a veces Bubble no persiste bien)
    json_string: str


@app.get("/health")
def health():
    return {"ok": True}


def _maybe_unescape_whitespace(text: str) -> str:
    """
    Bubble a veces envía el JSON como texto con secuencias literales \\n \\t \\r
    fuera de strings, ej: {\\n "a": 1 } -> eso NO es JSON válido.
    Convertimos esas secuencias a whitespace real.
    """
    t = (text or "").strip()
    if not t:
        return t

    # Heurística: si arranca con "{\n" escapado o contiene \n muy temprano
    if t.startswith("{\\n") or "\\n" in t[:200] or "\\t" in t[:200] or "\\r" in t[:200]:
        t = (
            t.replace("\\r\\n", "\n")
             .replace("\\n", "\n")
             .replace("\\t", "\t")
             .replace("\\r", "\n")
        )
    return t


def _parse_request_payload(text: str) -> Any:
    """
    Intenta parsear el body tolerando varios formatos típicos:
    - JSON normal
    - JSON con \\n escapados fuera de strings (Bubble)
    - JSON dentro de string
    - form-urlencoded: body=...
    - dict estilo Python con comillas simples
    """
    t = (text or "").strip()
    if not t:
        raise HTTPException(status_code=400, detail={"error": "Empty body"})

    # 0) Fix Bubble: convertir \\n literales a whitespace real (si aplica)
    t = _maybe_unescape_whitespace(t)

    # 1) JSON normal
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass

    # 2) form-urlencoded tipo "body=...."
    if t.startswith("body="):
        try:
            decoded = urllib.parse.unquote_plus(t[5:])
            decoded = _maybe_unescape_whitespace(decoded)
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
    # Caso: viene como string que contiene JSON
    if isinstance(payload, str):
        payload = _maybe_unescape_whitespace(payload)
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail={"error": "Body es string pero no JSON parseable", "preview": payload[:400]},
            )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail="Body debe ser un objeto JSON con datos_crudos y flags",
        )

    return payload


def _normalize_datos_crudos(datos_crudos: Any) -> Dict[str, Any]:
    if isinstance(datos_crudos, str):
        datos_crudos = _maybe_unescape_whitespace(datos_crudos)
        try:
            datos_crudos = json.loads(datos_crudos)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="datos_crudos inválido: JSON malformado")

    if not isinstance(datos_crudos, dict) or not datos_crudos:
        raise HTTPException(status_code=400, detail="datos_crudos requerido")

    return datos_crudos


@app.post("/compute", response_model=ComputeResponse)
async def compute(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    raw_bytes = await request.body()
    text = raw_bytes.decode("utf-8", errors="replace")

    # logs útiles en Render
    print("---- /compute content-type ----")
    print(request.headers.get("content-type"))
    print("---- /compute raw body preview ----")
    print(text.strip()[:400])
    print("---- end preview ----")

    payload_any = _parse_request_payload(text)
    payload = _normalize_payload(payload_any)

    datos_crudos = _normalize_datos_crudos(payload.get("datos_crudos"))
    flags = payload.get("flags") or {}
    if not isinstance(flags, dict):
        flags = {}

    raw, formatted, notes = compute_financials(datos_crudos, flags)

    base_response = {"raw": raw, "formatted": formatted, "notes": notes}

    # ✅ String JSON completo para Bubble (guardar/pasar sin depender de raw body text)
    json_string = json.dumps(base_response, ensure_ascii=False)

    response = {**base_response, "json_string": json_string}

    # Print complete response
    print("---- /compute RESPUESTA COMPLETA ----")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print("---- FIN RESPUESTA COMPLETA ----")
    print("---- /compute json_string length ----")
    print(len(json_string))
    print("---- FIN json_string length ----")

    return response


@app.post("/obtener-contexto")
async def obtener_contexto(
    body: ContextRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    # Misma validación de seguridad que /compute
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if faiss_index is None or textos_chunks is None:
        return {"contexto_pdf": "La base de conocimientos no está disponible. Ejecuta crear_indice.py primero."}

    if openai_client is None:
        return {"contexto_pdf": "OPENAI_API_KEY no configurada. No se pueden generar embeddings para la consulta."}

    # Preparar frase de búsqueda — intenta parsear el JSON crudo que envía Bubble
    frase_busqueda = body.query
    try:
        query_limpia = body.query.strip().replace("\\n", "").replace('\\"', '"')
        datos = json.loads(query_limpia)
        datos_crudos = datos.get("datos_crudos", {})
        tolerancia = datos_crudos.get("inversionista", {}).get("tolerancia_riesgo", "")
        ocupacion = datos_crudos.get("personal", {}).get("ocupacion", "")
        prioridades_list = datos_crudos.get("prioridades", [])
        prioridad_principal = prioridades_list[0] if prioridades_list else ""
        frase_busqueda = (
            f"Busca información, productos específicos y beneficios de la aseguradora ideales "
            f"para un cliente con perfil {tolerancia}, ocupación {ocupacion}, "
            f"y cuyas prioridades principales son {prioridad_principal}."
        )
        print(f"Frase generada para FAISS: {frase_busqueda}")
    except Exception as e:
        print(f"No se pudo parsear el JSON para la query. Usando raw query. Error: {e}")

    # Generar embedding de la consulta
    response = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[frase_busqueda],
    )
    query_vector = np.array([response.data[0].embedding], dtype="float32")

    # Buscar los 5 fragmentos más cercanos
    k = 5
    distances, indices = faiss_index.search(query_vector, k)

    fragmentos = []
    for idx in indices[0]:
        if 0 <= idx < len(textos_chunks):
            fragmentos.append(textos_chunks[idx])

    separador = "\n\n--- --- ---\n\n"
    contexto = separador.join(fragmentos)

    return {"contexto_pdf": contexto}
