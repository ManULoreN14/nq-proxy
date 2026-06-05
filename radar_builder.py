#!/usr/bin/env python3
"""
radar_builder.py — Genera datos_radar.json para la pestaña Horizontes
Lee manengis_tactico.json (ya generado por motor_manengis.py) y calcula:
  - Scores por horizonte: d2, d5, w1, w2, w3, w4
  - Scores por componente: tecnico, cot, volatilidad, macro, sentimiento
  - Amplitud de mercado y factor de exposición recomendado
  - Rangos de liquidez por horizonte (±N × ATR14)
  - Meta: risk_score, VIX, VIX TS, COT sesgo

Diseño:
  - Sin fuentes propias: reutiliza todas las variables de manengis_tactico.json
  - Aditivo: no modifica manengis_tactico.json
  - Tolerante a datos faltantes: usa fallbacks seguros
  - Scores en rango [-1, +1] (negativo=bajista, positivo=alcista)
"""

import json, datetime, math
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
INPUT_FILE   = SCRIPT_DIR / "manengis_tactico.json"
OUTPUT_FILE  = SCRIPT_DIR / "datos_radar.json"


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def utcnow_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"

def clamp(v, lo=-1.0, hi=1.0):
    """Pinza un valor al rango [lo, hi]."""
    if v is None: return 0.0
    return max(lo, min(hi, float(v)))

def safe(v, default=0.0):
    """Devuelve v si no es None/NaN, si no devuelve default."""
    if v is None: return default
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default

def estado_from_score(score):
    """Convierte score numérico [-1,+1] a string de estado."""
    if score >= 0.5:  return "alcista"
    if score >= 0.15: return "alcista_mod"
    if score <= -0.5: return "bajista"
    if score <= -0.15: return "bajista_mod"
    return "neutro"

def conf_from_score(score):
    """Convierte score a confianza porcentual [45, 80]."""
    abs_s = abs(safe(score))
    # 0 → 50%, 1 → 80%
    return round(50 + abs_s * 30)


# ─────────────────────────────────────────────────────────────────
# SCORE TÉCNICO  (rango -1 a +1)
# Señales: RSI, EMA trend, ROC5d, distancia desde máximo
# ─────────────────────────────────────────────────────────────────

def score_tecnico(v):
    """
    v = variables_crudas del JSON.
    Devuelve score en [-1, +1] y dict de señales.
    """
    puntos = 0.0
    max_puntos = 0.0
    senales = []

    # RSI14
    rsi = safe(v.get("rsi") or v.get("rsi_qqq"), None)
    if rsi is not None:
        max_puntos += 1.0
        if rsi < 30:
            puntos += 1.0; senales.append(f"RSI={rsi} sobrevendido → alcista")
        elif rsi > 70:
            puntos -= 1.0; senales.append(f"RSI={rsi} sobrecomprado → bajista")
        elif rsi > 55:
            puntos += 0.4; senales.append(f"RSI={rsi} zona alcista")
        elif rsi < 45:
            puntos -= 0.4; senales.append(f"RSI={rsi} zona bajista")
        else:
            senales.append(f"RSI={rsi} neutro")

    # EMA trend: precio vs EMA20 y EMA20 vs EMA50
    precio  = safe(v.get("precio_qqq"), None)
    ema20   = safe(v.get("ema20"), None)
    ema50   = safe(v.get("ema50"), None)
    if precio and ema20:
        max_puntos += 0.8
        if precio > ema20:
            puntos += 0.5; senales.append("Precio>EMA20 → alcista")
        else:
            puntos -= 0.5; senales.append("Precio<EMA20 → bajista")
    if ema20 and ema50:
        max_puntos += 0.6
        if ema20 > ema50:
            puntos += 0.4; senales.append("EMA20>EMA50 tendencia alcista")
        else:
            puntos -= 0.4; senales.append("EMA20<EMA50 tendencia bajista")

    # ROC5d (momentum 5 días)
    roc5d = safe(v.get("roc5d"), None)
    if roc5d is not None:
        max_puntos += 0.6
        if roc5d > 2:
            puntos += 0.5; senales.append(f"ROC5d=+{roc5d}% momentum alcista")
        elif roc5d < -2:
            puntos -= 0.5; senales.append(f"ROC5d={roc5d}% momentum bajista")
        elif roc5d > 0:
            puntos += 0.2
        else:
            puntos -= 0.2

    # Distancia desde máximo 60d
    dist_max = safe(v.get("dist_desde_max_pct"), None)
    if dist_max is not None:
        max_puntos += 0.5
        if dist_max < -15:
            puntos += 0.4; senales.append(f"dist_max={dist_max}% zona barrida → alcista potencial")
        elif dist_max < -8:
            puntos += 0.1
        elif dist_max > -2:
            puntos -= 0.2; senales.append(f"dist_max={dist_max}% cerca de máximos → cuidado")

    if max_puntos == 0: return 0.0, senales
    raw = puntos / max_puntos
    return clamp(raw), senales


# ─────────────────────────────────────────────────────────────────
# SCORE COT  (rango -1 a +1)
# Señales: sesgo leveraged money NQ + señal COT VIX
# ─────────────────────────────────────────────────────────────────

def score_cot(cot_nq, cot_vix):
    """
    cot_nq  = data["cot"]
    cot_vix = data["cot_vix"]
    Lógica contraria: especuladores muy largos → bajista; muy cortos → alcista.
    """
    puntos = 0.0; max_p = 0.0; senales = []

    # NQ COT
    if cot_nq and not cot_nq.get("error"):
        pct = safe(cot_nq.get("pct_largo"), None)
        sesgo = cot_nq.get("sesgo", "neutro")
        max_p += 1.0
        if sesgo == "bajista":          # specs muy largos → señal contraria bajista
            puntos -= 0.7; senales.append(f"COT NQ: specs {pct}% largos → bajista")
        elif sesgo == "alcista":        # specs muy cortos → señal contraria alcista
            puntos += 0.7; senales.append(f"COT NQ: specs {pct}% largos → alcista")
        else:
            senales.append(f"COT NQ: {pct}% largos → neutro")

    # VIX COT (lógica directa: specs largos VIX → bajista mercado)
    if cot_vix and not cot_vix.get("error"):
        senal_vix = cot_vix.get("senal", "neutro")
        max_p += 0.6
        if senal_vix == "bajista":      # specs largos VIX → bajista mercado
            puntos -= 0.5; senales.append("COT VIX: specs largos vola → bajista")
        elif senal_vix == "alcista":    # specs cortos VIX → alcista mercado
            puntos += 0.5; senales.append("COT VIX: specs cortos vola → alcista")
        else:
            senales.append("COT VIX: neutro")

    if max_p == 0: return 0.0, senales
    return clamp(puntos / max_p), senales


# ─────────────────────────────────────────────────────────────────
# SCORE VOLATILIDAD  (rango -1 a +1)
# Señales: VIX nivel, VIX Term Structure, VIX change 3d
# ─────────────────────────────────────────────────────────────────

def score_volatilidad(v, vts):
    """
    v   = variables_crudas
    vts = vix_term_structure
    """
    puntos = 0.0; max_p = 0.0; senales = []

    vix = safe(v.get("vix"), None)
    if vix is not None:
        max_p += 1.0
        if vix < 15:
            puntos += 0.6; senales.append(f"VIX={vix} complacencia baja")
        elif vix < 20:
            puntos += 0.3; senales.append(f"VIX={vix} zona normal")
        elif vix < 25:
            puntos -= 0.2; senales.append(f"VIX={vix} zona alerta")
        elif vix < 30:
            puntos -= 0.6; senales.append(f"VIX={vix} zona miedo")
        else:
            puntos += 0.4; senales.append(f"VIX={vix}>30 extremo → potencial rebote")

    # VIX Term Structure
    if vts and not vts.get("error"):
        estado = vts.get("estado", "sin_datos")
        back   = vts.get("backwardation", False)
        max_p += 0.8
        if estado == "contango_normal":
            puntos += 0.6; senales.append("VTS: contango_normal → alcista")
        elif estado == "contango_tenso":
            puntos += 0.2; senales.append("VTS: contango_tenso → neutro/alcista leve")
        elif back:
            puntos -= 0.8; senales.append("VTS: BACKWARDATION → bajista")

    return clamp(puntos / max(max_p, 0.01)), senales


# ─────────────────────────────────────────────────────────────────
# SCORE MACRO  (rango -1 a +1)
# Señales: curva 10Y-2Y, NFCI, HY Spread (vía risk_score parcial)
# ─────────────────────────────────────────────────────────────────

def score_macro(v, fred):
    """
    v    = variables_crudas
    fred = fred dict del JSON
    """
    puntos = 0.0; max_p = 0.0; senales = []

    # Curva 10Y-2Y
    sp_2_10 = safe(v.get("spread_2_10"), None)
    if sp_2_10 is not None:
        max_p += 0.8
        if sp_2_10 > 0.5:
            puntos += 0.6; senales.append(f"Curva={sp_2_10}% normal → alcista")
        elif sp_2_10 > 0:
            puntos += 0.2; senales.append(f"Curva={sp_2_10}% plana")
        elif sp_2_10 > -0.5:
            puntos -= 0.3; senales.append(f"Curva={sp_2_10}% invertida leve")
        else:
            puntos -= 0.6; senales.append(f"Curva={sp_2_10}% invertida profunda → bajista")

    # NFCI (National Financial Conditions Index)
    # Valor > 0 = condiciones más restrictivas (bajista)
    # Valor < 0 = condiciones más laxas (alcista)
    nfci = None
    if fred:
        nfci_block = fred.get("nfci", {})
        if isinstance(nfci_block, dict):
            nfci = safe(nfci_block.get("valor") or nfci_block.get("v"), None)
    if nfci is None:
        # Fallback a variables_crudas
        nfci = safe(v.get("nfci"), None)
    if nfci is not None:
        max_p += 0.7
        if nfci < -0.3:
            puntos += 0.6; senales.append(f"NFCI={nfci} condiciones muy laxas")
        elif nfci < 0:
            puntos += 0.3; senales.append(f"NFCI={nfci} condiciones laxas")
        elif nfci < 0.2:
            puntos -= 0.1; senales.append(f"NFCI={nfci} neutro/leve restrictivo")
        else:
            puntos -= 0.5; senales.append(f"NFCI={nfci} condiciones restrictivas → bajista")

    # HY Spread — extraer del bloque señales si disponible
    hy_spread = None
    if fred:
        for s in (fred.get("señales") or fred.get("senales") or []):
            if isinstance(s, dict) and "HY" in str(s.get("ind", "")):
                try:
                    hy_spread = float(str(s.get("val", "")).replace("%", ""))
                except (ValueError, TypeError):
                    pass
                break
    if hy_spread is not None:
        max_p += 0.5
        if hy_spread < 3.0:
            puntos += 0.4; senales.append(f"HY Spread={hy_spread}% bajo → alcista")
        elif hy_spread < 4.5:
            puntos += 0.1
        elif hy_spread < 6.0:
            puntos -= 0.3; senales.append(f"HY Spread={hy_spread}% elevado → bajista")
        else:
            puntos -= 0.5; senales.append(f"HY Spread={hy_spread}% zona stress")

    if max_p == 0: return 0.0, senales
    return clamp(puntos / max_p), senales


# ─────────────────────────────────────────────────────────────────
# SCORE SENTIMIENTO  (rango -1 a +1)
# Señales: Fear&Greed, similitud histórica (si fiable)
# ─────────────────────────────────────────────────────────────────

def score_sentimiento(fg, sim):
    """
    fg  = fear_greed dict
    sim = similitud_historica dict
    """
    puntos = 0.0; max_p = 0.0; senales = []

    # Fear & Greed (contraria: extremo miedo → alcista, extremo euforia → bajista)
    fg_score = safe(fg.get("score") if fg else None, None)
    if fg_score is not None:
        max_p += 1.0
        if fg_score < 20:
            puntos += 0.8; senales.append(f"F&G={fg_score} miedo extremo → alcista")
        elif fg_score < 35:
            puntos += 0.4; senales.append(f"F&G={fg_score} miedo → alcista leve")
        elif fg_score > 80:
            puntos -= 0.8; senales.append(f"F&G={fg_score} euforia extrema → bajista")
        elif fg_score > 65:
            puntos -= 0.4; senales.append(f"F&G={fg_score} optimismo → bajista leve")
        else:
            senales.append(f"F&G={fg_score} zona neutral")

    # Similitud histórica: usa distribución de vecinos
    if sim and sim.get("fiable"):
        dist = sim.get("distribucion", {})
        pct_ok  = safe(dist.get("ruido",  {}).get("porcentaje"), 0) + \
                  safe(dist.get("leve",   {}).get("porcentaje"), 0)
        pct_mal = safe(dist.get("fuerte", {}).get("porcentaje"), 0) + \
                  safe(dist.get("crash",  {}).get("porcentaje"), 0)
        max_p += 0.7
        if pct_ok >= 80:
            puntos += 0.6; senales.append(f"kNN: {pct_ok}% sin caídas → alcista")
        elif pct_ok >= 60:
            puntos += 0.2; senales.append(f"kNN: {pct_ok}% sin caídas → neutro/alcista")
        elif pct_mal >= 25:
            puntos -= 0.6; senales.append(f"kNN: {pct_mal}% precedieron corrección → bajista")
        elif pct_mal >= 15:
            puntos -= 0.2; senales.append(f"kNN: {pct_mal}% riesgo moderado")
        else:
            senales.append("kNN: distribución mixta")

    if max_p == 0: return 0.0, senales
    return clamp(puntos / max_p), senales


# ─────────────────────────────────────────────────────────────────
# DECAY TEMPORAL
# Los scores de horizontes lejanos convergen hacia 0 (= incertidumbre)
# usando un factor de decaimiento geométrico.
# ─────────────────────────────────────────────────────────────────

HORIZONS_DECAY = {
    "d2": 1.00,   # 0 días de decaimiento
    "d5": 0.88,   # ~12% menos convicción a 5d
    "w1": 0.72,   # ~28% menos a 1 semana
    "w2": 0.55,   # ~45% menos a 2 semanas
    "w3": 0.40,   # ~60% menos a 3 semanas
    "w4": 0.28,   # ~72% menos a 4 semanas
}

# Pesos de los 5 componentes para el score compuesto
PESOS = {
    "tecnico":     0.30,
    "cot":         0.20,
    "volatilidad": 0.20,
    "macro":       0.15,
    "sentimiento": 0.15,
}


# ─────────────────────────────────────────────────────────────────
# FACTOR DE EXPOSICIÓN  (Kelly simplificado 0.0 → 1.0)
# ─────────────────────────────────────────────────────────────────

def calc_factor_exposicion(score_compuesto, risk_score, breadth_pct50):
    """
    Combina el score del radar con el risk_score del motor para
    calcular un factor de exposición recomendado [0.0, 1.0].
    """
    # Base desde risk_score (0=verde, 10=rojo)
    base = max(0.0, 1.0 - safe(risk_score, 5) / 10.0)

    # Ajuste por score del radar: +/-10% según alcista/bajista
    ajuste = clamp(safe(score_compuesto, 0.0), -0.15, 0.15)

    # Ajuste por breadth: si >70% sobre EMA50 → +5%
    b50 = safe(breadth_pct50, 50)
    if b50 > 70:   ajuste += 0.05
    elif b50 < 35: ajuste -= 0.08

    resultado = clamp(base + ajuste, 0.10, 0.95)
    return round(resultado, 2)


# ─────────────────────────────────────────────────────────────────
# RANGOS POR HORIZONTE  (basados en ATR14)
# ─────────────────────────────────────────────────────────────────

ATR_MULTIPLIERS = {
    "d2": (0.8, 0.8),    # ±0.8×ATR
    "d5": (1.5, 1.5),    # ±1.5×ATR
    "w1": (2.0, 2.0),    # ±2.0×ATR
    "w2": (2.8, 2.8),    # ±2.8×ATR
    "w3": (3.5, 3.5),    # ±3.5×ATR
    "w4": (4.2, 4.2),    # ±4.2×ATR
}

def calc_rangos(precio_ndx, atr14):
    """
    Devuelve rangos soporte/resistencia NDX por horizonte basados en ATR.
    Usa precio NDX (más legible que QQQ para niveles).
    """
    if not precio_ndx or not atr14:
        return {}
    # ATR14 del QQQ escalado aproximado a NDX (ratio ~26× aprox)
    # Si tenemos ATR directo de NDX mejor, pero usamos el del motor (QQQ-based)
    # y lo escalamos: precio_ndx / precio_qqq ≈ ratio
    rangos = {}
    for hz, (mul_sup, mul_res) in ATR_MULTIPLIERS.items():
        atr_escalado = atr14  # en puntos QQQ; para NDX debería ser ~26x más alto
        # Como ATR está en QQQ y el precio NDX es ~26x, escalamos
        factor = precio_ndx / 470.0 if precio_ndx else 26  # 470 ≈ NDX/QQQ ratio típico
        atr_ndx = atr14 * factor
        rangos[hz] = {
            "sup":  round(precio_ndx - mul_sup * atr_ndx),
            "res":  round(precio_ndx + mul_res * atr_ndx),
        }
    return rangos



# ─────────────────────────────────────────────────────────────────
# BUILD_RENDER_KEYS
# Construye las 6 claves que el frontend espera en D (datos_radar.json)
# para que renderCOT, renderFRED/renderCurva, renderVixTS, renderTecnicos,
# renderPCR, renderOI y renderGEX tengan datos y no queden en blanco.
# Mapeo completo:
#   cot     ← data["cot"] + data["variables_crudas"]["cot_lev_net/cot_sesgo"]
#   vixTS   ← data["vix_term_structure"]
#   macro   ← data["fred"] + data["variables_crudas"][us10y/us30y/spread_2_10]
#   tecnicos← data["tecnicos"]
#   pcr     ← no disponible en manengis → objeto con error
#   opciones← no disponible en manengis → objeto con error + precio
# ─────────────────────────────────────────────────────────────────

def _vts_to_senal(estado, backwardation):
    """Traduce el estado VTS a la señal que espera renderVixTS()."""
    if backwardation:
        return "bajista"
    if estado == "contango_normal":
        return "alcista"
    if estado == "contango_tenso":
        return "neutro"
    if estado in ("backwardation_leve", "backwardation"):
        return "bajista"
    return "neutro"


def build_render_keys(data):
    """
    Devuelve un dict con exactamente las claves que el frontend espera:
      cot, vixTS, macro, tecnicos, pcr, opciones

    Regla: si no hay datos reales se incluye el objeto con error/null
    para que el frontend muestre "no disponible" en lugar de pantalla
    en blanco (que es el bug que este parche resuelve).
    """
    v       = data.get("variables_crudas", {})
    vts     = data.get("vix_term_structure", {})
    tec     = data.get("tecnicos", {})
    fred    = data.get("fred", {})
    cot_raw = data.get("cot", {})

    # ── 1. D.cot ─────────────────────────────────────────────────
    # renderCOT() usa: largos, cortos, neto, pctLargo, senal,
    #   cambioNeto, trend4w, netoDealers, senalDealers, desc, fecha
    cot_error = cot_raw.get("error") if cot_raw else "No disponible"
    cot_neto  = v.get("cot_lev_net")   # None si no hay datos
    cot_sesgo = v.get("cot_sesgo", "sin_datos")

    if cot_error and cot_neto is None:
        cot_block = {"error": cot_error}
    else:
        senal_cot = ("bajista" if cot_sesgo == "bajista"
                     else "alcista" if cot_sesgo == "alcista"
                     else "neutro")
        cot_block = {
            "neto":         cot_neto,
            "pctLargo":     None,
            "largos":       None,
            "cortos":       None,
            "senal":        senal_cot,
            "cambioNeto":   None,
            "trend4w":      None,
            "netoDealers":  None,
            "senalDealers": "neutro",
            "desc":         f"COT sesgo={cot_sesgo} · neto={cot_neto}",
            "fecha":        None,
        }

    # ── 2. D.vixTS ───────────────────────────────────────────────
    # renderVixTS() usa: spot, vix3m, vx1, vx2, spread1,
    #   backwardation, senal, vixPercentil, desc
    if vts and not vts.get("error"):
        back       = bool(vts.get("backwardation", False))
        spot       = vts.get("vix")      # "vix" es el campo spot en vix_term_structure
        v3m        = vts.get("vix3m")
        sp         = vts.get("spread")   # spread = vix3m - vix (positivo=contango)
        if sp is None and spot is not None and v3m is not None:
            try:
                sp = round(float(v3m) - float(spot), 2)
            except (TypeError, ValueError):
                sp = None
        estado_vts = vts.get("estado", "sin_datos")
        senal_vts  = _vts_to_senal(estado_vts, back)
        desc_vts   = (vts.get("descripcion") or
                      f"VIX={spot} / VIX3M={v3m}  ratio={vts.get('ratio')} · {estado_vts}")
        vixts_block = {
            "spot":          spot,
            "vix3m":         v3m,
            "vx1":           None,
            "vx2":           None,
            "spread1":       sp,
            "backwardation": back,
            "senal":         senal_vts,
            "vixPercentil":  None,
            "desc":          desc_vts,
        }
    else:
        vixts_block = {"error": "VIX TS no disponible"}

    # ── 3. D.macro ───────────────────────────────────────────────
    # renderFRED() usa: D.macro.score + D.macro.fred.*
    # renderCurva() usa: D.macro.curva.*
    fred_score = fred.get("score", 0) if fred else 0

    def _fred_val(block):
        """Extrae {v, trend} de bloque {valor, anterior} o devuelve None."""
        if not block or not isinstance(block, dict):
            return None
        val  = block.get("valor")
        prev = block.get("anterior")
        if val is None:
            return None
        trend = None
        if prev is not None:
            try:
                trend = "up" if float(val) > float(prev) else "down"
            except (TypeError, ValueError):
                pass
        return {"v": val, "trend": trend}

    fedfunds_block = _fred_val(fred.get("fedfunds", {})) if fred else None
    balance_block  = _fred_val(fred.get("balance_fed", {})) if fred else None

    us10y     = v.get("us10y")
    us30y     = v.get("us30y")
    sp2_10    = v.get("spread_2_10")
    curva_inv = bool(v.get("curva_invertida", False))

    curva_block = {
        "t3m":           None,
        "t5y":           None,
        "t10y":          us10y,
        "t30y":          us30y,
        "sp10_2":        sp2_10,
        "sp10_3m":       None,
        "invertida2y":   curva_inv,
        "invertida3m":   None,
        "senalRecesion": (fred.get("curva_descripcion") if fred else None),
    }

    macro_block = {
        "score": fred_score,
        "fred": {
            "walcl":         balance_block,
            "liquidez_neta": None,
            "fedfunds":      fedfunds_block,
            "hySpread":      None,
            "nfci":          None,
            "sofr":          None,
            "t5yie":         None,
            "t10yie":        None,
            "cpi_yoy":       None,
            "wlcflpcl":      None,
        },
        "curva": curva_block,
    }

    # ── 4. D.tecnicos ────────────────────────────────────────────
    # renderTecnicos() usa: D.tecnicos.d.* (diario), .w (semanal), .m (mensual)
    # manengis.tecnicos tiene: precio, rsi14, ema20, ema50, atr14, roc5d
    precio_tec = tec.get("precio") or v.get("precio_qqq")
    tecnicos_block = {
        "d": {
            "precio":    precio_tec,
            "rsi14":     tec.get("rsi14"),
            "macd":      None,
            "stoch":     None,
            "bb":        None,
            "roc5":      tec.get("roc5d"),
            "roc10":     None,
            "roc20":     None,
            "volRatio5": None,
            "ema8":      None,
            "ema21":     tec.get("ema20"),   # ema20 del motor ≈ ema21 para el frontend
            "ema50":     tec.get("ema50"),
            "ema100":    None,
            "ema200":    None,
        },
        "w": None,
        "m": None,
    }

    # ── 5. D.pcr ─────────────────────────────────────────────────
    # renderPCR() usa: total, equity, desc, error, fuente
    pcr_block = {
        "error":  "No disponible",
        "total":  None,
        "equity": None,
        "desc":   None,
        "fuente": None,
    }

    # ── 6. D.opciones ────────────────────────────────────────────
    # renderOI()       usa: v1.{topCalls, topPuts, maxPain, senal}, precio
    # renderGEX()      usa: opciones.gex.{valor, estado, desc, trampa}
    # renderDerivados()usa: gex_real, skew, ratio_0dte
    opciones_block = {
        "error":      "No disponible",
        "precio":     v.get("precio_qqq"),
        "v1":         None,
        "v2":         None,
        "gex":        None,
        "gex_real":   None,
        "skew":       None,
        "ratio_0dte": None,
    }

    return {
        "cot":      cot_block,
        "vixTS":    vixts_block,
        "macro":    macro_block,
        "tecnicos": tecnicos_block,
        "pcr":      pcr_block,
        "opciones": opciones_block,
    }

# ─────────────────────────────────────────────────────────────────
# BUILDER PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def build():
    # Cargar manengis_tactico.json
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"No se encuentra {INPUT_FILE}")

    data = json.loads(INPUT_FILE.read_text(encoding="utf-8"))

    v   = data.get("variables_crudas", {})
    vts = data.get("vix_term_structure", {})
    cot_nq  = data.get("cot", {})
    cot_vix = data.get("cot_vix", {})
    fg  = data.get("fear_greed", {})
    sim = data.get("similitud_historica", {})
    rc  = data.get("risk_compuesto", {})
    br  = data.get("breadth", {})
    fred = data.get("fred", {})

    # ── Calcular los 5 scores de componente ───────────────────────────────
    s_tec, _  = score_tecnico(v)
    s_cot, _  = score_cot(cot_nq, cot_vix)
    s_vol, _  = score_volatilidad(v, vts)
    s_mac, _  = score_macro(v, fred)
    s_sen, _  = score_sentimiento(fg, sim)

    scores_comp = {
        "tecnico":     round(s_tec, 3),
        "cot":         round(s_cot, 3),
        "volatilidad": round(s_vol, 3),
        "macro":       round(s_mac, 3),
        "sentimiento": round(s_sen, 3),
    }

    # ── Score compuesto ponderado ──────────────────────────────────────────
    score_base = sum(scores_comp[k] * PESOS[k] for k in PESOS)
    score_base = clamp(score_base)

    # ── Scores por horizonte (con decaimiento temporal) ───────────────────
    horizontes = {}
    for hz, decay in HORIZONS_DECAY.items():
        sc = round(clamp(score_base * decay), 3)
        horizontes[hz] = {
            "score": sc,
            "estado": estado_from_score(sc),
            "conf":   conf_from_score(sc),
        }

    # ── Componentes para la UI ────────────────────────────────────────────
    componentes = {
        "tecnico":     {"score": scores_comp["tecnico"],     "peso": PESOS["tecnico"],     "label": "Técnico"},
        "cot":         {"score": scores_comp["cot"],         "peso": PESOS["cot"],         "label": "COT"},
        "volatilidad": {"score": scores_comp["volatilidad"], "peso": PESOS["volatilidad"], "label": "Volatilidad"},
        "macro":       {"score": scores_comp["macro"],       "peso": PESOS["macro"],       "label": "Macro FRED"},
        "sentimiento": {"score": scores_comp["sentimiento"], "peso": PESOS["sentimiento"], "label": "Sentimiento"},
    }

    # ── Amplitud de mercado ───────────────────────────────────────────────
    pct_ema20 = safe(br.get("pct_sobre_ema20") if br else v.get("breadth_pct_ema20"), 50)
    pct_ema50 = safe(br.get("pct_sobre_ema50") if br else None, 50)
    risk_score = safe(rc.get("valor") if rc else v.get("risk_score"), 5.0)

    factor_exp = calc_factor_exposicion(score_base, risk_score, pct_ema50)

    if pct_ema50 > 70:
        breadth_desc = f"Breadth sólido: {pct_ema50}% componentes sobre EMA50. Amplia participación alcista."
    elif pct_ema50 > 50:
        breadth_desc = f"Breadth moderado: {pct_ema50}% sobre EMA50. Mayoría alcista pero no desbocado."
    elif pct_ema50 > 35:
        breadth_desc = f"Breadth débil: {pct_ema50}% sobre EMA50. Participación limitada."
    else:
        breadth_desc = f"Breadth deteriorado: {pct_ema50}% sobre EMA50. Mercado amplio bajista."

    amplitud = {
        "factor_exposicion_recomendado": factor_exp,
        "pct_sobre_ema20": pct_ema20,
        "pct_sobre_ema50": pct_ema50,
        "descripcion": breadth_desc,
    }

    # ── Liquidez / Rangos ─────────────────────────────────────────────────
    precio_qqq = safe(v.get("precio_qqq"), None)
    precio_ndx = safe(v.get("precio_ndx"), None)
    atr14      = safe(v.get("atr14"), None)

    # Si no tenemos NDX, derivar aproximación desde QQQ
    if precio_ndx is None and precio_qqq:
        precio_ndx = round(precio_qqq * 26.0)

    rangos = calc_rangos(precio_ndx, atr14)

    liquidez = {
        "atr14":             round(atr14, 2) if atr14 else None,
        "rangosPorHorizonte": rangos,
    }

    # ── Precio ────────────────────────────────────────────────────────────
    roc5d  = safe(v.get("roc5d"), None)
    precio = {
        "qqq":       precio_qqq,
        "ndx":       precio_ndx,
        "cambio_pct": round(roc5d / 5, 2) if roc5d is not None else None,
    }

    # ── Meta ──────────────────────────────────────────────────────────────
    vix    = safe(v.get("vix"), None)
    vts_estado = vts.get("estado", "sin_datos") if vts else "sin_datos"
    cot_sesgo  = cot_nq.get("sesgo", "sin_datos") if cot_nq and not cot_nq.get("error") else "sin_datos"

    meta = {
        "risk_score_manengis": risk_score,
        "vix":                 round(vix, 2) if vix else None,
        "vix_ts":              vts_estado,
        "cot_sesgo":           cot_sesgo,
        "semaforo":            data.get("plan_exposicion", {}).get("semaforo", "sin_datos"),
        "regimen":             data.get("regimen", {}).get("regimen", "sin_datos"),
    }

    # ── Claves de render para sub-pestañas Inst/Macro/Técnico ──────────
    # Mapea campos de manengis_tactico.json a las claves que usan
    # renderCOT, renderFRED, renderVixTS, renderTecnicos, renderPCR,
    # renderOI y renderGEX.  Sin estas claves esas pestañas quedaban vacías.
    render_keys = build_render_keys(data)

    # ── Documento final ───────────────────────────────────────────────────
    doc = {
        "generado": utcnow_str(),
        "version": "1.1",
        "fuente": "radar_builder.py / datos desde manengis_tactico.json",
        "precio": precio,
        "scores": {
            "horizontes":  horizontes,
            "componentes": componentes,
            "compuesto":   round(score_base, 3),
        },
        "amplitud_mercado": amplitud,
        "liquidez":         liquidez,
        "meta":             meta,
        # Campo de frescura para updateFreshness() del frontend
        "ts":               utcnow_str(),
        # ── Claves de render (sub-pestañas Inst / Macro / Técnico) ───────
        # Consumidas directamente por renderCOT, renderFRED, renderCurva,
        # renderVixTS, renderTecnicos, renderPCR, renderOI, renderGEX.
        **render_keys,
    }
    return doc


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  radar_builder.py — generando datos_radar.json")
    print("=" * 55)

    try:
        doc = build()
    except FileNotFoundError as e:
        print(f"\n  ERROR: {e}")
        print("  Asegúrate de que motor_manengis.py ha corrido antes.")
        raise SystemExit(1)
    except Exception as e:
        import traceback
        print(f"\n  ERROR inesperado: {e}")
        traceback.print_exc()
        raise SystemExit(1)

    OUTPUT_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    h  = doc["scores"]["horizontes"]
    sc = doc["scores"]["compuesto"]
    f  = doc["amplitud_mercado"]["factor_exposicion_recomendado"]
    m  = doc["meta"]

    print(f"\n  JSON guardado: {OUTPUT_FILE.name}")
    print(f"  Score compuesto: {sc:+.3f}  |  Factor exposición: {f*100:.0f}%")
    print(f"  Horizontes:")
    for hz_id, hz_data in h.items():
        print(f"    {hz_id}: {hz_data['score']:+.3f}  {hz_data['estado']:<15}  conf={hz_data['conf']}%")
    print(f"  Risk MANENGIS: {m['risk_score_manengis']}  |  VIX: {m['vix']}  |  VTS: {m['vix_ts']}")
    print(f"  COT sesgo: {m['cot_sesgo']}  |  Semáforo: {m['semaforo']}")
    print("=" * 55)
