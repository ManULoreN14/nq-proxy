#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exportar_para_ia.py — Parte 3 de IDEAS_FUTURAS_NQ_UNIFIED.md

Genera SNAPSHOT_IA_YYYYMMDD.md a partir de datos_radar.json: un resumen en
Markdown pensado para pegarlo en una conversación con una IA y usarla de
"profesor" sobre los datos reales del día, no sobre teoría genérica.

Es de SOLO LECTURA sobre datos_radar.json — no toca actualizar_radar.py,
preparar_datos.py, ni ningún otro archivo de producción. Cero riesgo.

Uso:
    python exportar_para_ia.py
    python exportar_para_ia.py --json C:\\ruta\\datos_radar.json --out C:\\ruta\\salida
    python exportar_para_ia.py --sin-comparar

Por defecto:
    - Busca datos_radar.json en el directorio actual.
    - Busca el SNAPSHOT_IA_*.md más reciente en el directorio de salida para
      narrar el cambio respecto al día anterior (Parte 3.3). Si no encuentra
      ninguno, simplemente omite esa sección sin avisar de error.
    - Escribe SNAPSHOT_IA_YYYYMMDD.md en el directorio actual.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════
# GLOSARIO — una línea por término, integrado en el propio documento
# ══════════════════════════════════════════════════════════════════════════
GLOSARIO = {
    "PCR": "Put/Call Ratio. Ratio de opciones put vs call negociadas. Alto = "
           "mucha cobertura bajista comprada (miedo); bajo = poca cobertura "
           "(complacencia). Se usa de forma CONTRARIAN: extremos altos "
           "suelen preceder rebotes, extremos bajos suelen preceder caídas.",
    "DIX": "Dark Pool Index (SqueezeMetrics). % de volumen que se ejecuta "
           "fuera de bolsa (dark pools), donde operan más las instituciones. "
           "Alto = acumulación institucional; bajo = distribución.",
    "GEX": "Gamma Exposure de los creadores de mercado (dealers). Positivo = "
           "los dealers venden en subidas y compran en caídas (amortigua "
           "movimientos, mercado 'pegado'). Negativo = compran en subidas y "
           "venden en caídas (amplifica movimientos, más volatilidad).",
    "VVIX": "Volatilidad del VIX (la 'vol de la vol'). Mide el nerviosismo "
            "en el propio mercado de opciones sobre volatilidad. Disparado "
            "= pánico; muy bajo = complacencia.",
    "VIX Term Structure": "Comparación entre el VIX spot y los futuros de "
            "VIX a distintos vencimientos. CONTANGO (futuros > spot) = "
            "mercado tranquilo, normal. BACKWARDATION (futuros < spot) = "
            "estrés agudo de corto plazo, suele preceder rebotes.",
    "COT": "Commitments of Traders (CFTC). Posicionamiento semanal de "
           "grandes especuladores (leveraged funds) en futuros. Extremos "
           "de posicionamiento se leen de forma CONTRARIAN: muy largos = "
           "riesgo de caída (long squeeze); muy cortos = riesgo de subida "
           "(short squeeze).",
    "SKEW": "Índice SKEW de CBOE. Mide el precio relativo de las opciones "
            "muy fuera de dinero (protección ante caídas extremas / cisne "
            "negro). Alto = el mercado paga caro por seguros de cola.",
    "Sentimiento Contrario": "Oscilador compuesto -100/+100 (DIX+VTS+VVIX/"
            "VIX+COT, ponderado por IC medido). Alto = miedo extremo "
            "(contrarian alcista); bajo = complacencia extrema (contrarian "
            "bajista). Modo observación: no pesa todavía en el score.",
    "Flujos ICI": "Entradas/salidas semanales de TODA la industria de "
            "fondos+ETF de EE.UU. (Investment Company Institute), no "
            "específico de QQQ/Nasdaq. Da contexto de apetito de riesgo "
            "agregado del mercado. Sí pesa en el score de flujos.",
    "Amplitud de mercado": "Cuántos valores participan de un movimiento del "
            "índice, no solo el índice en sí. Precio subiendo con amplitud "
            "cayendo (menos valores acompañando) es una divergencia bajista "
            "clásica.",
    "Kelly / Exposición efectiva": "Porcentaje de capital recomendado según "
            "el criterio de Kelly, ajustado por volatilidad. Es el tamaño "
            "de posición sugerido, no una orden automática.",
    "Régimen macro": "Clasificación del entorno financiero general "
            "(expansión / desaceleración / estrés / crisis) a partir de "
            "condiciones financieras (NFCI), crédito (HY spread), curva de "
            "tipos y liquidez de la Fed.",
    "Liquidez neta Fed": "WALCL (balance de la Fed) menos TGA (cuenta del "
            "Tesoro) menos RRP (repo inverso). Aproxima cuánta liquidez "
            "real hay disponible para los mercados; drenándose = viento en "
            "contra estructural.",
    "kNN Predictor": "Busca en el histórico los N días más parecidos al día "
            "actual (por VIX-TS, VVIX, DIX, GEX, SKEW, RSI, etc.) y resume "
            "qué pasó después en esos análogos. Es estadística descriptiva "
            "de similitud, no una predicción garantizada.",
}


# ══════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════════
def g(d, *path, default=None):
    """Acceso seguro anidado: g(D, 'cot', 'neto') -> D['cot']['neto'] o default."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def fnum(v, nd=2, suf=""):
    if v is None:
        return "no disponible"
    try:
        return f"{v:.{nd}f}{suf}"
    except (ValueError, TypeError):
        return str(v)


def pct_lectura(p):
    """Traduce un percentil (0-100) a una lectura en palabras."""
    if p is None:
        return None
    if p <= 10:
        return f"percentil {p} (extremadamente bajo)"
    if p <= 25:
        return f"percentil {p} (bajo)"
    if p <= 75:
        return f"percentil {p} (rango normal)"
    if p <= 90:
        return f"percentil {p} (alto)"
    return f"percentil {p} (extremadamente alto)"


def buscar_snapshot_anterior(out_dir: Path, hoy_str: str):
    """Devuelve el path del SNAPSHOT_IA_*.md más reciente distinto al de hoy,
    o None si no hay ninguno. No lanza excepción si el directorio no existe."""
    if not out_dir.exists():
        return None
    candidatos = sorted(out_dir.glob("SNAPSHOT_IA_*.md"))
    candidatos = [c for c in candidatos if hoy_str not in c.name]
    return candidatos[-1] if candidatos else None


def extraer_valor_snapshot(texto, etiqueta):
    """Extrae un valor numérico simple de una línea tipo '**ETIQUETA**: valor'
    o '**ETIQUETA** = valor' del snapshot anterior, para la comparación
    Parte 3.3. Best-effort: si no lo encuentra, devuelve None sin fallar."""
    m = re.search(re.escape(etiqueta) + r"\*{0,2}\s*[:=]\s*([\-\+]?[\d\.]+)", texto)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════
# CONSTRUCCIÓN DE SECCIONES
# ══════════════════════════════════════════════════════════════════════════
def seccion_cabecera(D, fecha_str):
    precio = D.get("precio") or {}
    ndx = precio.get("ndx")
    qqq = precio.get("qqq")
    vix = precio.get("vix")
    scores = D.get("scores") or {}
    score_final = scores.get("final") if isinstance(scores, dict) else None
    regimen = D.get("regimen_macro") or {}
    regimen_txt = regimen.get("es") if isinstance(regimen, dict) else regimen
    amp = D.get("amplitud_mercado") or {}
    exposicion = amp.get("factor_exposicion_recomendado")

    lines = [
        f"# SNAPSHOT PARA IA-PROFESOR · {fecha_str}",
        "",
        "> Documento generado automáticamente para pegar en una conversación "
        "con una IA y usarla como profesor sobre los datos reales de hoy. "
        "No es un volcado de JSON: cada cifra viene con su contexto.",
        "",
        "## Resumen del día",
        "",
        f"- **NDX**: {fnum(ndx, 0)} · **QQQ**: {fnum(qqq, 2)} · **VIX**: {fnum(vix, 1)}",
        f"- **Régimen macro**: {regimen_txt or 'no disponible'}",
        f"- **Score compuesto**: {fnum(score_final, 2)}",
        f"- **Exposición recomendada (Kelly ajustado)**: "
        f"{fnum(exposicion * 100, 0, '%') if exposicion is not None else 'no disponible'}",
        "",
    ]
    return "\n".join(lines)


def seccion_metricas(D):
    lines = ["## Métricas con contexto", ""]

    # PCR
    pcr = D.get("pcr") or {}
    pcr_csv = D.get("csv_qqq_opciones") or {}
    pcr_val = pcr.get("total") if pcr.get("total") is not None else pcr_csv.get("pcr")
    pcr_pct = g(pcr, "percentil_historico")
    if pcr_val is not None:
        lectura = pct_lectura(pcr_pct)
        extra = f", {lectura}" if lectura else ""
        lines.append(f"- **PCR** = {fnum(pcr_val, 2)}{extra} · señal: "
                      f"{pcr.get('señal', 'no disponible')}")
    else:
        lines.append("- **PCR**: no disponible")

    # DIX / GEX
    dixgex = D.get("csv_dix_gex") or {}
    if dixgex.get("dix") is not None:
        lectura = pct_lectura(dixgex.get("dix_percentil"))
        extra = f", {lectura}" if lectura else ""
        lines.append(f"- **DIX** = {fnum(dixgex.get('dix'), 1, '%')}{extra} · "
                      f"señal: {dixgex.get('dix_señal', 'no disponible')}")
    if dixgex.get("gex_b") is not None:
        lines.append(f"- **GEX** = {fnum(dixgex.get('gex_b'), 2, 'B$')} · "
                      f"señal: {dixgex.get('gex_señal', 'no disponible')}")

    # VIX Term Structure
    vts = D.get("vixTermStructure") or {}
    if vts.get("spot") is not None:
        back = "SÍ (backwardation)" if vts.get("backwardation") else "NO (contango)"
        lines.append(f"- **VIX Term Structure**: spot={fnum(vts.get('spot'), 1)}, "
                      f"VX1={fnum(vts.get('vx1'), 1)} · ¿backwardation? {back}")

    # VVIX / SKEW
    vvskew = D.get("csv_vix_vvix_skew") or {}
    if vvskew.get("vvix") is not None:
        lines.append(f"- **VVIX** = {fnum(vvskew.get('vvix'), 1)}")
    if vvskew.get("skew") is not None:
        lines.append(f"- **SKEW** = {fnum(vvskew.get('skew'), 1)}")

    # COT
    cot = D.get("cot") or {}
    cot_csv = D.get("csv_cot") or {}
    if cot.get("neto") is not None:
        lectura = pct_lectura(g(cot_csv, "percentil_historico"))
        extra = f", {lectura}" if lectura else ""
        lines.append(f"- **COT (leveraged funds)**: neto={cot.get('neto')}{extra} "
                      f"({cot.get('pctLargo', '—')}% largos) · señal: "
                      f"{cot.get('señal', cot.get('señalDealers', 'no disponible'))}")

    # Sentimiento Contrario
    sc = D.get("csv_sentimiento_contrario") or {}
    if sc.get("valor") is not None:
        lines.append(f"- **Índice Sentimiento Contrario** = {sc.get('valor')} "
                      f"({sc.get('interpretacion', '')}) · modo observación, "
                      f"no pesa todavía en el score")

    # Flujos ICI
    ici = D.get("flujos_ici") or {}
    if ici.get("suma_4sem_equity_millones") is not None:
        lines.append(f"- **Flujos ICI (industria completa)**: "
                      f"{ici['suma_4sem_equity_millones']:+.0f}M en 4 semanas · "
                      f"señal: {ici.get('señal', 'no disponible')}")

    # Amplitud
    amp = D.get("amplitud_mercado") or {}
    if amp.get("zscore_qqq_sma200") is not None:
        lines.append(f"- **Amplitud (z-score QQQ vs SMA200)** = "
                      f"{fnum(amp.get('zscore_qqq_sma200'), 2)} · señal: "
                      f"{amp.get('señal_zscore', 'no disponible')}")

    # Giro técnico
    giro = D.get("giro") or {}
    señal_giro = giro.get("señalGlobal") or giro.get("senalGlobal")
    if señal_giro:
        lines.append(f"- **Detectores de giro**: señal global = {señal_giro}")

    lines.append("")
    return "\n".join(lines)


def seccion_conflictos(D):
    """Detecta pares de señales que apuntan en direcciones distintas y las
    explica en una frase, en vez de dejar que el lector las cruce solo."""
    lines = ["## Señales en conflicto", ""]
    conflictos = []

    cot = D.get("cot") or {}
    amp = D.get("amplitud_mercado") or {}
    sc = D.get("csv_sentimiento_contrario") or {}
    giro = D.get("giro") or {}
    ici = D.get("flujos_ici") or {}

    cot_señal = (cot.get("señal") or "").lower()
    amp_señal = (amp.get("señal_zscore") or "").lower()
    if "alcista" in cot_señal and "distribu" in amp_señal:
        conflictos.append(
            "El COT sugiere sesgo contrarian alcista (posicionamiento extremo "
            "en un lado), pero la amplitud de mercado está en distribución — "
            "tensión entre posicionamiento y participación real del mercado."
        )
    if sc.get("valor") is not None and ici.get("señal"):
        sc_val = sc["valor"]
        ici_s = ici["señal"]
        if sc_val > 30 and "bajista" in ici_s:
            conflictos.append(
                f"El Sentimiento Contrario está en zona de miedo ({sc_val}, "
                f"contrarian alcista) pero los flujos ICI muestran salidas "
                f"reales de la industria — el posicionamiento dice una cosa, "
                f"el dinero real se está moviendo en la otra dirección."
            )
        elif sc_val < -30 and "alcista" in ici_s:
            conflictos.append(
                f"El Sentimiento Contrario está en zona de complacencia "
                f"({sc_val}, contrarian bajista) pero los flujos ICI siguen "
                f"entrando — el mercado luce complaciente en derivados pero "
                f"el dinero real sigue llegando."
            )
    señal_giro = (giro.get("señalGlobal") or giro.get("senalGlobal") or "").lower()
    if señal_giro == "techo" and "alcista" in cot_señal:
        conflictos.append(
            "Los detectores de giro marcan posible techo técnico mientras el "
            "COT sigue en sesgo contrarian alcista — conviene vigilar si el "
            "giro técnico se confirma antes de fiarse solo del posicionamiento."
        )

    if not conflictos:
        lines.append("No se han detectado conflictos evidentes entre las "
                      "señales principales disponibles hoy.")
    else:
        for c in conflictos:
            lines.append(f"- {c}")
    lines.append("")
    return "\n".join(lines)


def seccion_comparativa(D, snapshot_anterior_path):
    """Parte 3.3: compara valores clave contra el snapshot anterior si existe."""
    lines = ["## Respecto al snapshot anterior", ""]
    if not snapshot_anterior_path:
        lines.append("No se encontró un snapshot anterior para comparar — "
                      "esta sección se completará a partir de la próxima ejecución.")
        lines.append("")
        return "\n".join(lines)

    try:
        texto_anterior = snapshot_anterior_path.read_text(encoding="utf-8")
    except Exception as e:
        lines.append(f"No se pudo leer el snapshot anterior ({snapshot_anterior_path.name}): {e}")
        lines.append("")
        return "\n".join(lines)

    comparaciones = []

    score_actual = g(D, "scores", "final")
    score_ant = extraer_valor_snapshot(texto_anterior, "Score compuesto")
    if score_actual is not None and score_ant is not None:
        delta = score_actual - score_ant
        direccion = "hacia alcista" if delta > 0 else "hacia bajista" if delta < 0 else "sin cambio"
        comparaciones.append(f"El score compuesto pasó de {score_ant} a "
                              f"{score_actual} ({delta:+.2f}, {direccion}).")

    sc_actual = g(D, "csv_sentimiento_contrario", "valor")
    sc_ant = extraer_valor_snapshot(texto_anterior, "Índice Sentimiento Contrario")
    if sc_actual is not None and sc_ant is not None:
        comparaciones.append(f"El Índice de Sentimiento Contrario pasó de "
                              f"{sc_ant} a {sc_actual} ({sc_actual - sc_ant:+.1f}).")

    if not comparaciones:
        lines.append(f"Se encontró un snapshot anterior ({snapshot_anterior_path.name}) "
                      f"pero no se pudieron extraer suficientes valores comparables.")
    else:
        lines.extend(f"- {c}" for c in comparaciones)
        lines.append(f"\n_(comparado contra `{snapshot_anterior_path.name}`)_")
    lines.append("")
    return "\n".join(lines)


def seccion_glosario():
    lines = ["## Glosario", ""]
    for termino, definicion in GLOSARIO.items():
        lines.append(f"- **{termino}**: {definicion}")
    lines.append("")
    return "\n".join(lines)


def seccion_preguntas(D):
    lines = ["## Preguntas sugeridas para arrancar el diálogo", ""]
    preguntas = [
        "¿Qué factor domina hoy el score compuesto y por qué?",
        "¿Hay alguna señal en conflicto que merezca más atención que las demás?",
        "Si el Sentimiento Contrario está en zona neutral, ¿qué señales sí aportan información hoy?",
    ]
    amp = D.get("amplitud_mercado") or {}
    if amp.get("factor_exposicion_recomendado") is not None:
        preguntas.append("¿Por qué la exposición recomendada por Kelly es la que es, dado el resto de señales?")
    for p in preguntas:
        lines.append(f"- {p}")
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════
def generar_snapshot(json_path: Path, out_dir: Path, comparar: bool = True) -> Path:
    with open(json_path, encoding="utf-8") as f:
        D = json.load(f)

    ts = D.get("ts")
    if ts:
        try:
            fecha_dt = datetime.fromisoformat(ts)
        except ValueError:
            fecha_dt = datetime.now()
    else:
        fecha_dt = datetime.now()

    hoy_str = fecha_dt.strftime("%Y%m%d")
    fecha_legible = fecha_dt.strftime("%Y-%m-%d %H:%M")

    snapshot_anterior = buscar_snapshot_anterior(out_dir, hoy_str) if comparar else None

    partes = [
        seccion_cabecera(D, fecha_legible),
        seccion_metricas(D),
        seccion_conflictos(D),
        seccion_comparativa(D, snapshot_anterior),
        seccion_glosario(),
        seccion_preguntas(D),
    ]

    contenido = "\n".join(partes)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"SNAPSHOT_IA_{hoy_str}.md"
    out_path.write_text(contenido, encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Exporta SNAPSHOT_IA_YYYYMMDD.md desde datos_radar.json")
    ap.add_argument("--json", default="datos_radar.json", help="Ruta a datos_radar.json")
    ap.add_argument("--out", default=".", help="Directorio de salida")
    ap.add_argument("--sin-comparar", action="store_true", help="No comparar con el snapshot anterior")
    args = ap.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"ERROR: no se encontró {json_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_path = generar_snapshot(json_path, out_dir, comparar=not args.sin_comparar)
    print(f"[OK] Generado: {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
