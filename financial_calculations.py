from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple, List
import math
import re


FUTUROS_COMPROMISOS_DESC = "Compromisos futuros anualizados según lo declarado"


def _parse_numeric_fragment(fragment: str) -> float:
    """
    Intenta parsear un fragmento numérico que puede contener separadores de miles y texto alrededor.
    """
    candidate = fragment.rstrip(".,")
    if "." in candidate and "," in candidate:
        if candidate.rfind(",") > candidate.rfind("."):
            candidate = candidate.replace(".", "")
            candidate = candidate.replace(",", ".")
        else:
            candidate = candidate.replace(",", "")
    else:
        candidate = candidate.replace(",", ".")

    if candidate.count(".") > 1:
        # asumir el último punto como decimal y eliminar separadores previos
        parts = candidate.split(".")
        decimal_part = parts[-1]
        head = "".join(parts[:-1])
        sign = "-" if head.startswith("-") else ""
        head_digits = re.sub(r"\D", "", head.lstrip("-"))
        integer_part = head_digits or "0"
        candidate = f"{sign}{integer_part}.{decimal_part}"

    try:
        return float(candidate)
    except Exception:
        return 0.0


def _to_float(v: Any) -> float:
    """
    Convierte números que puedan venir como:
    - int/float
    - strings "1234.56" o "1,234.56" o "1.234,56"
    - strings con símbolos "$", "%", espacios, etc.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return float(v)

    s = str(v).strip()
    if s == "":
        return 0.0

    # quitar símbolos comunes
    s = s.replace("$", "").replace("%", "").strip()

    # si viene como "1.234.567,89" (ES)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})*(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return 0.0

    # si viene como "1,234,567.89" (EN)
    if re.fullmatch(r"-?\d{1,3}(,\d{3})*(\.\d+)?", s):
        s = s.replace(",", "")
        try:
            return float(s)
        except Exception:
            return 0.0

    # fallback: intentar normalizar coma decimal
    s2 = s.replace(",", ".")
    try:
        return float(s2)
    except Exception:
        match = re.search(r"-?\d[\d.,]*", s)
        if match:
            return _parse_numeric_fragment(match.group())
        return 0.0


def _fmt_money_es(value: float) -> str:
    """
    Monetario: miles con punto, decimales con coma, 2 decimales.
    Ej: 1234567.89 -> "1.234.567,89"
    """
    value = 0.0 if (math.isnan(value) or math.isinf(value)) else float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    s = f"{value:,.2f}"  # "1,234,567.89"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")  # -> "1.234.567,89"
    return sign + s


def _fmt_percent_es(value: float) -> str:
    value = 0.0 if (math.isnan(value) or math.isinf(value)) else float(value)
    s = f"{value:.2f}".replace(".", ",")
    return f"{s}%"


def _fmt_number_es(value: float, decimals: int = 2) -> str:
    value = 0.0 if (math.isnan(value) or math.isinf(value)) else float(value)
    s = f"{value:.{decimals}f}".replace(".", ",")
    return s


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _get(d: Dict[str, Any], *keys: str) -> float:
    for k in keys:
        if k in d:
            return _to_float(d.get(k))
    return 0.0


def compute_financials(datos_crudos: Dict[str, Any], flags: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """
    Implementa los cálculos del prompt original (enfoque anterior), separando:
    - raw: números puros
    - formatted: strings ya formateadas para pintar en el JSON final
    """
    notes: List[str] = []

    economico = (datos_crudos or {}).get("economico") or {}
    patrimonial = (datos_crudos or {}).get("patrimonial") or {}

    # --- Inputs (economico) ---
    ingresos_fijos = _get(economico, "ingresos_fijos")
    ingresos_variables = _get(economico, "ingresos_variables")
    prestaciones_fijas = _get(economico, "prestaciones_fijas")
    prestaciones_variables = _get(economico, "prestaciones_variables")
    egresos_fijos = _get(economico, "egresos_fijos")
    egresos_variables = _get(economico, "egresos_variables")

    # crédito / deuda
    credito_mensual = _get(economico, "credito_mensual", "pago_mensual_deuda")
    credito_anual_in = _get(economico, "credito_anual")
    if credito_mensual == 0 and credito_anual_in != 0:
        credito_mensual = credito_anual_in / 12.0
        notes.append("credito_mensual no venía; se derivó de credito_anual/12.")

    if bool(flags.get("credito_incluido_en_egresos")):
        if credito_mensual != 0:
            notes.append("credito_incluido_en_egresos=true: se forzó credito_mensual=0 para evitar doble conteo.")
        credito_mensual = 0.0

    # futuros compromisos (normalización única: anual > mensual*12 > 0)
    # prioridad: futuros_compromisos_anual (nuevo) sobre futuros_compromisos_total_anual (legado)
    futuros_total_anual = _get(economico, "futuros_compromisos_anual", "futuros_compromisos_total_anual")
    futuros_mensual = _get(economico, "futuros_compromisos_mensual")

    if futuros_total_anual == 0.0 and futuros_mensual != 0.0:
        futuros_total_anual = futuros_mensual * 12.0
    if bool(flags.get("futuros_compromisos_incluido_en_egresos")):
        if futuros_total_anual != 0:
            notes.append("futuros_compromisos_incluido_en_egresos=true: se forzó futuros_compromisos_total_anual=0 para evitar doble conteo.")
        futuros_total_anual = 0.0

    # --- Inputs (patrimonial) ---
    activos_inmobiliarios = _get(patrimonial, "activos_inmobiliarios")
    activos_desgaste_rapido = _get(patrimonial, "activos_desgaste_rapido")
    inversiones = _get(patrimonial, "inversiones")
    sociedades_y_acciones = _get(patrimonial, "sociedades_y_acciones")
    fondo_emergencia = _get(patrimonial, "fondo_emergencia")
    if fondo_emergencia == 0.0:
        fondo_emergencia = _get(economico, "fondo_emergencia")

    seguro_vida = _get(patrimonial, "seguro_vida")
    valor_seguro_auto = _get(patrimonial, "valor_seguro_auto")
    seguros_accidentes_personales = _get(patrimonial, "seguros_accidentes_personales")
    seguro_inmuebles = _get(patrimonial, "seguro_inmuebles")
    gastos_funeral = _get(patrimonial, "gastos_funeral")
    plan_retiro_sa = _get(patrimonial, "plan_retiro_sa")
    plan_ahorro_sa = _get(patrimonial, "plan_ahorro_sa")
    persona_clave_sa = _get(patrimonial, "persona_clave_sa")
    intersocios_sa = _get(patrimonial, "intersocios_sa")
    suma_asegurada_gmm = _get(patrimonial, "suma_asegurada_gmm")

    # --- Cálculos 2.1 INGRESOS ---
    ingresos_totales_mensuales = ingresos_fijos + ingresos_variables
    ingresos_totales_anuales = ingresos_totales_mensuales * 12.0

    prestaciones_totales_mensuales = prestaciones_fijas + prestaciones_variables
    prestaciones_totales_anuales = prestaciones_totales_mensuales * 12.0

    ingresos_globales_mensuales = ingresos_totales_mensuales + prestaciones_totales_mensuales
    ingresos_globales_anuales = ingresos_globales_mensuales * 12.0

    # --- 2.2 EGRESOS ---
    egresos_globales_mensuales = egresos_variables + egresos_fijos
    egresos_globales_anuales = egresos_globales_mensuales * 12.0

    # --- 2.3 Fondo de emergencia vs ingresos ---
    if ingresos_totales_mensuales <= 0:
        porc_emergencia = 0.0
        meses_cubiertos = 0.0
    else:
        porc_emergencia = (fondo_emergencia / ingresos_totales_mensuales) * 100.0
        meses_cubiertos = fondo_emergencia / ingresos_totales_mensuales

    # --- 2.5 Crédito ---
    credito_anual = credito_mensual * 12.0

    # --- 2.6 Balances ---
    futuros_mensual_equiv = futuros_total_anual / 12.0
    balance_mensual_operativo = ingresos_globales_mensuales - egresos_globales_mensuales
    balance_total_mensual = balance_mensual_operativo - credito_mensual
    balance_total_anual = balance_total_mensual * 12.0
    balance_global = balance_total_mensual - futuros_mensual_equiv
    # --- 2.7 Patrimonio y protección ---
    patrimonio_total = (
        activos_inmobiliarios
        + activos_desgaste_rapido
        + inversiones
        + sociedades_y_acciones
        + fondo_emergencia
    )

    proteccion_total = (
        seguro_vida
        + 0.60 * valor_seguro_auto
        + seguros_accidentes_personales
        + seguro_inmuebles
        + gastos_funeral
        + plan_retiro_sa
        + plan_ahorro_sa
        + persona_clave_sa
        + intersocios_sa
        + 0.02 * suma_asegurada_gmm
    )

    if patrimonio_total <= 0:
        porc_cobertura = 0.0
    else:
        porc_cobertura = (proteccion_total / patrimonio_total) * 100.0

    riesgo_patrimonial_porcentaje = _clamp(100.0 - porc_cobertura, 0.0, 100.0)

    # nivel riesgo por cobertura
    if porc_cobertura <= 45:
        nivel_riesgo = "Alto"
    elif porc_cobertura <= 80:
        nivel_riesgo = "Moderado"
    else:
        nivel_riesgo = "Bajo"

    # --- Formateo ---
    formatted = {
        "operacion_final": {
            "ingresos_mensuales_fijos": _fmt_money_es(ingresos_fijos),
            "ingresos_mensuales_variables": _fmt_money_es(ingresos_variables),
            "ingresos_totales": _fmt_money_es(ingresos_totales_mensuales),
            "prestaciones_totales": _fmt_money_es(prestaciones_totales_mensuales),
            "ingresos_globales": _fmt_money_es(ingresos_globales_mensuales),
            "egresos_globales": _fmt_money_es(egresos_globales_mensuales),
            "futuros_compromisos": FUTUROS_COMPROMISOS_DESC,
            "futuros_compromisos_total": f"{_fmt_money_es(futuros_total_anual)} (anual)",
            "credito_mensual": _fmt_money_es(credito_mensual),
            "credito_anual": _fmt_money_es(credito_anual),
        },
        "balance_total": _fmt_money_es(balance_total_mensual),
        "balance_global": _fmt_money_es(balance_global),
        "fondo_de_emergencia": f"{_fmt_percent_es(porc_emergencia)} ({_fmt_number_es(meses_cubiertos, 2)} meses de ingresos equivalentes)",
        "operaciones_perfil_patrimonial": {
            "patrimonio_total": _fmt_money_es(patrimonio_total),
            "proteccion_total": _fmt_money_es(proteccion_total),
            "nivel_riesgo_patrimonial": nivel_riesgo,
            "riesgo_patrimonial_porcentaje": round(riesgo_patrimonial_porcentaje, 2),
            "activos_desgaste_rapido": _fmt_money_es(activos_desgaste_rapido),
            "activos_inmobiliarios": _fmt_money_es(activos_inmobiliarios),
            "inversiones": _fmt_money_es(inversiones),
            "sociedades_y_acciones": _fmt_money_es(sociedades_y_acciones),
        },
    }

    raw = {
        "ingresos_fijos": ingresos_fijos,
        "ingresos_variables": ingresos_variables,
        "prestaciones_fijas": prestaciones_fijas,
        "prestaciones_variables": prestaciones_variables,
        "egresos_fijos": egresos_fijos,
        "egresos_variables": egresos_variables,
        "ingresos_totales_mensuales": ingresos_totales_mensuales,
        "prestaciones_totales_mensuales": prestaciones_totales_mensuales,
        "ingresos_globales_mensuales": ingresos_globales_mensuales,
        "egresos_globales_mensuales": egresos_globales_mensuales,
        "credito_mensual": credito_mensual,
        "credito_anual": credito_anual,
        "futuros_compromisos_total_anual": futuros_total_anual,
        "balance_mensual_operativo": balance_mensual_operativo,
        "balance_total_mensual": balance_total_mensual,
        "balance_total_anual": balance_total_anual,
        "balance_global": balance_global,
        "fondo_emergencia": fondo_emergencia,
        "porc_emergencia": porc_emergencia,
        "meses_cubiertos": meses_cubiertos,
        "patrimonio_total": patrimonio_total,
        "proteccion_total": proteccion_total,
        "porc_cobertura": porc_cobertura,
        "riesgo_patrimonial_porcentaje": riesgo_patrimonial_porcentaje,
        "nivel_riesgo_patrimonial": nivel_riesgo,
    }

    return raw, formatted, notes
