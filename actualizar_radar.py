"""
╔══════════════════════════════════════════════════════════════════════════════╗
║     NQ MULTI-HORIZONTE RADAR CUANTITATIVO — FASE 1-7 + CAPA CSV LOCAL       ║
║     Script: actualizar_radar.py  (UNIFICADO v8.0)                            ║
║     Ruta:   C:\\Users\\m21lo\\PROYECTO_NASDAQ_UNIFICADO\\actualizar_radar.py     ║
║     Autor:  Sistema Cuantitativo — Arquitectura Hibrida Local+Vercel         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  INTEGRACION v8.0 (esta version unifica dos scripts):                       ║
║    - Toda la logica de actualizar_radar.py  (Yahoo, FRED, MRM, scores...)   ║
║    - Toda la logica de actualizar_radar_csv.py  (CSV locales: COT, VIX,      ║
║      VVIX, SKEW, DIX, GEX, QQQ opciones Barchart)                            ║
║                                                                              ║
║  REGLA DE PRECEDENCIA: si un bloque se calcula desde CSV local Y desde      ║
║  API/Yahoo (COT, VIX, opciones QQQ, PCR), PREVALECE el CSV. La logica       ║
║  online queda como FALLBACK automatico cuando los CSV no estan disponibles. ║
║                                                                              ║
║  RUTA CSV LOCAL: BASE_DIR / "DATOS_CSV" / (configurable mas abajo)          ║
║    COT/             *.txt (CFTC)                                             ║
║    DIX.csv          (SqueezeMetrics)                                         ║
║    VIX_History.csv  (CBOE)                                                   ║
║    VVIX_History.csv (CBOE)                                                   ║
║    skew-history.csv (CBOE)                                                   ║
║    qqq_quotedata.csv(Barchart)                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

FASE 1  Columna vertebral funcional:
  OK Carga incremental (init desde 2000 + delta diario)
  OK Tecnico: EMAs, RSI, MACD, Bollinger, ATR, OBV, Stoch, Vol relativo
  OK VIX Term Structure · Scores 2D/5D/1S/2S/3S/4S · Git push automatico

FASE 2  Macro profundo (FRED):
  OK Liquidez Neta = WALCL - WTREGEN - RRPONTSYD
  OK Tipos reales DFII10, inflacion CPIAUCSL, curva 3M/5Y/10Y/30Y
  OK HY Credit Spread, NFCI, DXY correlacion movil 30/90d con QQQ

FASE 3  Derivados + Institucional:
  OK COT via CFTC Socrata API (Non-Commercial + Dealers)
  OK Opciones QQQ: MaxPain 3 vencimientos, GEX sintetico, PCR CBOE

FASE 4  Market Regime Matching (Crisis Fingerprint Engine):
  OK Matriz de features historicos desde 2000 (RSI, MACD, BB, VIX, TLT, HYG)
  OK Normalizacion Z-score rolling · Similitud coseno + euclidiana
  OK Catalogo: Punto Com 2000, Crisis 2008, COVID 2020, Bear 2022...

FASE 5  Amplitud + Kelly:
  OK Ratio Cobre/Oro · ZScore QQQ vs SMA200 · Sesgo estacional
  OK Kelly simplificado x VIX scalar → factor_exposicion_recomendado

FASE 6  Alertas + UI:
  OK Alertas email Gmail SMTP · Banner alertas · Footer dinamico

FASE 7  Modulos avanzados:
  OK A0 Validacion calendario mercado (mercado_abierto_hoy)
  OK A1 Forward Fill explicito para APIs FRED
  OK A2 FRED nuevas series: WLCFLPCL (ventanilla descuento) + CPI YoY
  OK A3 Proxy liquidez China: CNY=X + SOXX
  OK A4 Amplitud NDX-100 real: Net New Highs/Lows 52W
  OK A5 SEC Insiders: Form 4 Big Tech 90 dias
  OK A6 GEX real por strike con gamma_flip_level
  OK A7 SKEW de opciones (put OTM-5% / call OTM+5%)
  OK A8 0DTE ratio sobre primeros 10 vencimientos
  OK A9 CTA Trigger Levels Donchian 20/50
  OK A10 Alertas email nivel 2 (VIX, cisne, kelly, dealers, breadth)
  OK A11 VERSION = 7.0-fase7 · fase_activa = 7
  OK A12 Score amplitud integra ndx100_breadth + proxy_china

Uso:
  python actualizar_radar.py                   # Ejecucion normal (CSV + APIs)
  python actualizar_radar.py --init            # Forzar descarga historica completa desde 2000
  python actualizar_radar.py --nogit           # Saltar el push a GitHub
  python actualizar_radar.py --noinstitucional # Saltar modulos lentos (NDX100 breadth + SEC)
  python actualizar_radar.py --nocsv           # Saltar capa CSV (usar solo APIs/Yahoo)
  python actualizar_radar.py --solocsv         # Solo CSV (saltar APIs lentas: NDX100, SEC, FRED, Yahoo)
"""

import os
import sys
import json
import subprocess
import logging
import argparse
import warnings
from pathlib import Path
from datetime import datetime, timedelta, date

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR       = Path(__file__).resolve().parent
HISTORICO_PATH = BASE_DIR / "historico_maestro.csv"
JSON_PATH      = BASE_DIR / "datos_radar.json"
LOG_PATH       = BASE_DIR / "radar.log"

FECHA_INICIO   = "2000-01-01"
VERSION        = "8.0-unificado"

# ─────────────────────────────────────────────────────────────────────────────
#  RUTAS CSV LOCALES — CAPA AUTORITATIVA (prevalece sobre APIs)
# ─────────────────────────────────────────────────────────────────────────────
#  Estos CSV son la fuente PRINCIPAL del sistema. Cuando esten disponibles,
#  sus datos SOBRESCRIBEN los calculados desde Yahoo/CFTC API. Si no estan,
#  las funciones online actuan como fallback automatico.
# ─────────────────────────────────────────────────────────────────────────────

DATA_CSV_DIR = BASE_DIR / "DATOS_CSV"      # Carpeta raiz con todos los CSV
COT_CSV_DIR  = DATA_CSV_DIR / "COT"        # Subcarpeta con los .txt del CFTC
DIX_CSV      = DATA_CSV_DIR / "DIX.csv"           # SqueezeMetrics (date,price,dix,gex)
VIX_CSV      = DATA_CSV_DIR / "VIX_History.csv"   # CBOE spot diario
VVIX_CSV     = DATA_CSV_DIR / "VVIX_History.csv"  # CBOE VVIX diario
SKEW_CSV     = DATA_CSV_DIR / "skew-history.csv"  # CBOE SKEW diario
QQQ_OPC_CSV  = DATA_CSV_DIR / "qqq_quotedata.csv" # Barchart QQQ opciones (descarga diaria)

# ─── CONFIGURACION ALERTAS EMAIL (FASE 6) ─────────────────────────────────
EMAIL_FROM     = ""   # Gmail origen: tu@gmail.com
EMAIL_TO       = ""   # Destino: tu@gmail.com
EMAIL_PASSWORD = ""   # App Password de Gmail (no la contrasena normal)
EMAIL_ALERTAS  = False  # Cambiar a True para activar alertas por email

FRED_API_KEY   = "f15ed9ee86d337183138a81bfd4952cb"  # Free key FRED

# Símbolos Yahoo Finance
SIMBOLOS = {
    "NDX":  "^NDX",
    "QQQ":  "QQQ",
    "SPY":  "SPY",
    "IWM":  "IWM",
    "VIX":  "^VIX",
    "VXN":  "^VXN",
    "VIX3M":"^VIX3M",
    "TNX":  "^TNX",
    "IRX":  "^IRX",
    "FVX":  "^FVX",
    "TYX":  "^TYX",
    "DXY":  "DX-Y.NYB",
    "GLD":  "GLD",
    "TLT":  "TLT",
    "HYG":  "HYG",
    "EEM":  "EEM",
    "GC":   "GC=F",       # Oro Futuros (Fase 2)
    "SOXX": "SOXX",       # Semiconductores (Fase 2)
    "HG":   "HG=F",       # Cobre Futuros (Fase 5)
    "CNY":  "CNY=X",      # Yuan Chino (Fase 7 — proxy liquidez PBoC)
}

# Series FRED a descargar
FRED_SERIES = {
    # Liquidez Fed
    "WALCL":        "Balance total Fed (activos totales)",
    "WTREGEN":      "TGA — Cuenta General del Tesoro",
    "RRPONTSYD":    "RRP — Repos Inversos overnight",
    # Tipos y política monetaria
    "FEDFUNDS":     "Fed Funds Rate efectivo",
    "SOFR":         "SOFR — tasa overnight garantizada",
    # Inflación y tipos reales
    "DFII10":       "Tipo real 10Y (TIPS breakeven)",
    "CPIAUCSL":     "IPC EEUU — Inflación",
    "T5YIE":        "Expectativas de inflación 5Y",
    "T10YIE":       "Expectativas de inflación 10Y",
    "T5YIFR":       "Forward inflacion 5Y5Y",
    # Curva de tipos (spreads)
    "T10Y2Y":       "Spread 10Y-2Y",
    "T10Y3M":       "Spread 10Y-3M",
    # Crédito y condiciones financieras
    "BAMLH0A0HYM2": "HY Credit Spread (ICE BofA)",
    "NFCI":         "NFCI — Índice condiciones financieras Chicago Fed",
    # Tipos de mercado
    "DGS3MO":       "Rendimiento T-Bill 3 meses",
    "DGS5":         "Rendimiento bono 5 años",
    "DGS10":        "Rendimiento bono 10 años",
    "DGS30":        "Rendimiento bono 30 años",
    "DGS2":         "Rendimiento bono 2 años",
    # Fase 7 — nuevas series
    "WLCFLPCL":     "Ventanilla Descuento Fed — estres bancario",
}

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)



# ─────────────────────────────────────────────────────────────────────────────
#  ALERTAS EMAIL — FASE 6
# ─────────────────────────────────────────────────────────────────────────────

def enviar_alerta_email(modulo: str, error: str, url_fuente: str = "") -> bool:
    """Envia alerta por email via Gmail SMTP cuando un modulo critico falla.
    Activa solo cuando EMAIL_ALERTAS = True y credenciales configuradas.
    """
    if not EMAIL_ALERTAS:
        return False
    if not EMAIL_FROM or not EMAIL_TO or not EMAIL_PASSWORD:
        log.warning("  [Email] No configurado (EMAIL_FROM/TO/PASSWORD vacios)")
        return False
    try:
        import smtplib, ssl
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        asunto = "[NQ Radar ALERTA] Modulo " + modulo + " - Error " + ahora
        cuerpo = (
            "NQ RADAR CUANTITATIVO - ALERTA AUTOMATICA v" + VERSION + "\n"
            + "=" * 60 + "\n"
            + "Modulo afectado : " + modulo + "\n"
            + "Error           : " + error + "\n"
            + "Fecha/Hora      : " + ahora + "\n"
            + "Fuente oficial  : " + (url_fuente if url_fuente else "No especificada") + "\n\n"
            + "Accion recomendada:\n"
            + "  1. Verificar la fuente oficial: " + url_fuente + "\n"
            + "  2. Revisar logs en: " + str(LOG_PATH) + "\n"
            + "  3. Ejecutar el script manualmente para reintentar.\n\n"
            + "---\nGenerado automaticamente por actualizar_radar.py\n"
        )
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg.attach(MIMEText(cuerpo, "plain", "utf-8"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as srv:
            srv.login(EMAIL_FROM, EMAIL_PASSWORD)
            srv.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info("  [Email] Alerta enviada a " + EMAIL_TO + " — Modulo: " + modulo)
        return True
    except Exception as ex:
        log.warning("  [Email] Fallo al enviar alerta: " + str(ex))
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  DESCARGA DE DATOS — YAHOO FINANCE
# ─────────────────────────────────────────────────────────────────────────────

def descargar_datos(ticker: str, inicio: str, fin: str | None = None) -> pd.DataFrame:
    """Descarga OHLCV de Yahoo Finance para un ticker dado."""
    try:
        import yfinance as yf
        fin_str = fin or date.today().strftime("%Y-%m-%d")
        df = yf.download(
            ticker,
            start=inicio,
            end=fin_str,
            progress=False,
            auto_adjust=True,
            actions=False,
        )
        if df.empty:
            log.warning(f"  [!] Sin datos para {ticker}")
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df.index.name = "fecha"
        df.index = pd.to_datetime(df.index).normalize()
        df = df[df["close"].notna()].copy()
        log.info(f"  ✓ {ticker}: {len(df)} filas ({inicio} → {fin_str})")
        return df

    except Exception as e:
        log.error(f"  ✗ Error descargando {ticker}: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
#  DESCARGA DE DATOS — FRED API
# ─────────────────────────────────────────────────────────────────────────────

def descargar_fred(series_id: str, inicio: str = "2000-01-01") -> pd.Series:
    """
    Descarga una serie de FRED (Federal Reserve de St. Louis).
    Devuelve pd.Series con índice DatetimeIndex.
    """
    try:
        import requests
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}"
            f"&api_key={FRED_API_KEY}"
            f"&file_type=json"
            f"&observation_start={inicio}"
            f"&sort_order=asc"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        obs = data.get("observations", [])
        if not obs:
            log.warning(f"  [!] FRED {series_id}: sin observaciones")
            return pd.Series(dtype=float)

        df = pd.DataFrame(obs)
        df = df[df["value"] != "."].copy()
        df["date"]  = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.set_index("date")["value"].dropna()
        df.index = df.index.normalize()
        log.info(f"  ✓ FRED {series_id}: {len(df)} obs ({df.index[0].date()} → {df.index[-1].date()})")
        return df

    except Exception as e:
        log.error(f"  ✗ Error FRED {series_id}: {e}")
        return pd.Series(dtype=float)


def descargar_fred_ultimo(series_id: str, n: int = 3) -> dict | None:
    """Obtiene los últimos N valores de una serie FRED. Más rápido para datos recientes."""
    try:
        import requests
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}"
            f"&api_key={FRED_API_KEY}"
            f"&file_type=json"
            f"&limit={n}"
            f"&sort_order=desc"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
        if not obs:
            return None
        v0 = float(obs[0]["value"])
        v1 = float(obs[1]["value"]) if len(obs) > 1 else None
        return {
            "v":     round(v0, 4),
            "prev":  round(v1, 4) if v1 is not None else None,
            "fecha": obs[0]["date"],
            "trend": ("up" if v0 > v1 else "down") if v1 is not None else None,
        }
    except Exception as e:
        log.warning(f"  [!] FRED último {series_id}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 7 — A0  Validacion de calendario de mercado
# ─────────────────────────────────────────────────────────────────────────────

def estado_sesion_mercado() -> dict:
    """Clasifica el estado de la sesion de mercado USA HOY.

    Devuelve dict con:
      - 'estado': 'sesion_en_curso' | 'cierre_disponible' | 'premercado_laboral'
                  | 'fin_de_semana' | 'festivo_probable' | 'indeterminado'
      - 'ejecutar': bool — si el script DEBE continuar o no
      - 'ultima_fecha': str ISO de la ultima vela disponible para QQQ (o None)
      - 'descripcion': str legible para log

    Politica:
      - Sabado/Domingo  -> ejecutar=True (refrescar JSON con ultima vela del viernes)
      - L-V con datos   -> ejecutar=True (sesion en curso o cierre disponible)
      - L-V SIN datos   -> ejecutar=True (premercado: NY abre 15:30 CEST; trabajamos
                           con el ultimo cierre disponible)
      - Festivo USA detectado por ausencia de datos en dia laboral -> ejecutar=True
        igualmente (queremos regenerar el JSON con datos del dia previo)

    Esto sustituye a la antigua mercado_abierto_hoy(): ya NO abortamos el script
    porque yfinance no tenga vela del dia; trabajamos con la ultima disponible.
    """
    from datetime import date as date_cls, timedelta
    hoy = date_cls.today()
    wd  = hoy.weekday()  # 0=lun, 6=dom

    # 1) Fin de semana → no buscamos vela de hoy, simplemente usamos la ultima
    if wd >= 5:
        return {
            "estado": "fin_de_semana",
            "ejecutar": True,
            "ultima_fecha": None,
            "descripcion": "Fin de semana — mercado USA cerrado. Se regenera el JSON con la ultima vela disponible.",
        }

    # 2) Dia laboral: intentamos averiguar si Yahoo ya tiene la vela de hoy
    try:
        import yfinance as yf
        # Pedimos 5 dias para garantizar que siempre haya algo (period maneja
        # festivos y fines de semana sin lanzar error)
        df = yf.download("QQQ", period="5d", progress=False, auto_adjust=True)
        if df.empty:
            return {
                "estado": "indeterminado",
                "ejecutar": True,
                "ultima_fecha": None,
                "descripcion": "yfinance devolvio vacio para QQQ (5d). Se continua usando historico local como ultima referencia.",
            }
        ultima = pd.to_datetime(df.index[-1]).date()
        ultima_str = ultima.strftime("%Y-%m-%d")

        if ultima == hoy:
            # Hay barra para hoy. Puede ser sesion en curso o ya cerrada.
            # Distinguimos por hora UTC (NY cierra a las 20:00 UTC = 22:00 CEST verano).
            import datetime as _dt
            ahora_utc = _dt.datetime.utcnow()
            if 13 <= ahora_utc.hour < 20:
                estado_str = "sesion_en_curso"
                desc = f"Sesion USA en curso (vela parcial de {ultima_str} disponible)."
            else:
                estado_str = "cierre_disponible"
                desc = f"Cierre USA de {ultima_str} ya disponible."
            return {"estado": estado_str, "ejecutar": True,
                    "ultima_fecha": ultima_str, "descripcion": desc}
        else:
            # No hay vela de hoy todavia (premercado) o es festivo USA
            dif_dias = (hoy - ultima).days
            if dif_dias == 1:
                desc = (f"Premercado USA en dia laboral (ultima vela: {ultima_str}). "
                        f"NY abre 15:30 CEST. Se trabaja con esa vela como ultima referencia.")
                estado_str = "premercado_laboral"
            else:
                desc = (f"Posible festivo USA o gap de datos ({dif_dias} dias desde {ultima_str}). "
                        f"Se regenera el JSON con la ultima vela disponible.")
                estado_str = "festivo_probable"
            return {"estado": estado_str, "ejecutar": True,
                    "ultima_fecha": ultima_str, "descripcion": desc}

    except Exception as e:
        # yfinance fallo: en dia laboral asumimos premercado y continuamos
        return {
            "estado": "indeterminado",
            "ejecutar": True,
            "ultima_fecha": None,
            "descripcion": f"No se pudo consultar yfinance ({e}). Se continua con historico local.",
        }


def mercado_abierto_hoy() -> bool:
    """Compatibilidad hacia atras: devuelve True si la sesion esta en curso o
    ya hay cierre disponible para hoy. Para la logica nueva usa
    estado_sesion_mercado() que es mas rica.
    """
    return estado_sesion_mercado()["estado"] in ("sesion_en_curso", "cierre_disponible")


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 7 — A1  Forward Fill explicito para series FRED criticas
# ─────────────────────────────────────────────────────────────────────────────

def fred_con_fallback(series_id: str, df_historico: "pd.DataFrame",
                      col_nombre: str, n: int = 3) -> "dict | None":
    """Intenta obtener el ultimo valor de FRED.
    Si falla, hace Forward Fill desde historico_maestro.csv local.
    Nunca devuelve None si hay datos historicos disponibles.
    """
    resultado = descargar_fred_ultimo(series_id, n=n)
    if resultado is not None:
        return resultado
    # Fallback: ultimo valor conocido del CSV local
    if col_nombre in df_historico.columns:
        serie = df_historico[col_nombre].dropna()
        if len(serie) > 0:
            v = float(serie.iloc[-1])
            log.warning(f"  [FwdFill] {series_id} -> usando ultimo valor local: {v}")
            return {"v": v, "prev": None, "fecha": "forward_fill", "trend": None}
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 7 — A3  Proxy liquidez China: CNY=X + SOXX
# ─────────────────────────────────────────────────────────────────────────────

def calcular_proxy_china(df: "pd.DataFrame") -> dict:
    """
    Proxy de liquidez PBoC/China:
    Cruza la cotizacion del Yuan (CNY=X) con el sector semiconductores (SOXX).
    Yuan fuerte (CNY baja) + SOXX sube = liquidez asiatica fluyendo al NASDAQ.
    Yuan debil (CNY sube) + SOXX cae = restriccion liquidez china.
    """
    try:
        import yfinance as yf

        cny_col = None
        soxx_col = None
        for col in df.columns:
            cu = col.upper()
            if "CNY" in cu and "CLOSE" in cu:
                cny_col = df[col].dropna()
            if "SOXX" in cu and "CLOSE" in cu:
                soxx_col = df[col].dropna()

        # Si CNY no esta en el historico, descargarlo
        if cny_col is None or len(cny_col) < 20:
            cny_raw = yf.download("CNY=X", period="6mo", progress=False, auto_adjust=True)
            if not cny_raw.empty:
                if isinstance(cny_raw.columns, pd.MultiIndex):
                    cny_raw.columns = [c[0] for c in cny_raw.columns]
                cny_col = cny_raw["Close"].dropna()

        if cny_col is None or soxx_col is None or len(cny_col) < 20 or len(soxx_col) < 20:
            return {"senal": "neutro", "score": 0.0, "error": "datos_insuficientes"}

        # Alinear series por fecha
        aligned = pd.concat([cny_col, soxx_col], axis=1, join="inner").dropna()
        aligned.columns = ["cny", "soxx"]
        if len(aligned) < 20:
            return {"senal": "neutro", "score": 0.0, "error": "datos_insuficientes"}

        # ROC 20 dias de cada serie
        roc_cny  = round((aligned["cny"].iloc[-1] / aligned["cny"].iloc[-21] - 1) * 100, 2)
        roc_soxx = round((aligned["soxx"].iloc[-1] / aligned["soxx"].iloc[-21] - 1) * 100, 2)

        # Correlacion movil 30d
        ret = aligned.pct_change().dropna()
        corr_30d = round(float(ret.tail(30)["cny"].corr(ret.tail(30)["soxx"])), 3) \
                   if len(ret) >= 30 else None

        # Señal compuesta
        if roc_cny < -0.5 and roc_soxx > 1.0:
            senal = "liquidez_positiva"
            desc  = "Yuan fortaleciendose + semis subiendo - liquidez asiatica fluyendo al QQQ"
            score = 1.5
        elif roc_cny > 0.5 and roc_soxx < -1.0:
            senal = "liquidez_negativa"
            desc  = "Yuan debilitandose + semis cayendo - restriccion liquidez china, presion NASDAQ"
            score = -1.5
        elif roc_soxx > 2.0:
            senal = "semis_liderando"
            desc  = "Semiconductores liderando - viento de cola tecnologico"
            score = 1.0
        else:
            senal = "neutro"
            desc  = "Sin senal clara de liquidez asiatica"
            score = 0.0

        log.info("  [China] roc_cny=" + str(roc_cny) + "% roc_soxx=" + str(roc_soxx) + "% senal=" + senal)

        return {
            "roc_cny_20d":      roc_cny,
            "roc_soxx_20d":     roc_soxx,
            "corr_cny_soxx_30d": corr_30d,
            "senal":            senal,
            "desc":             desc,
            "score":            score,
            "fuente":           "proxy_pboc_cny_soxx",
            "error":            None
        }
    except Exception as e:
        log.warning("  [China] Proxy PBoC fallo: " + str(e))
        return {"senal": "neutro", "score": 0.0, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 7 — A4  Amplitud NASDAQ-100 real: Net New Highs/Lows 52W
# ─────────────────────────────────────────────────────────────────────────────

def calcular_amplitud_ndx100(df: "pd.DataFrame") -> dict:
    """
    Calcula Net New Highs - New Lows de 52 semanas sobre los 100
    componentes del Nasdaq-100. Usa historico local cuando posible,
    yfinance como fallback.
    """
    NDX100_TICKERS = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","COST",
        "ASML","NFLX","AMD","PEP","LIN","QCOM","ADBE","INTU","CSCO","TXN",
        "AMGN","BKNG","ISRG","CMCSA","HON","VRTX","REGN","GILD","MU","LRCX",
        "ADI","KLAC","PANW","SNPS","CDNS","MELI","ORLY","CTAS","MNST","FTNT",
        "MDLZ","MAR","ABNB","WDAY","KDP","AEP","PYPL","CRWD","TEAM","DXCM",
        "FAST","ODFL","GEHC","ROST","IDXX","PAYX","EXC","BIIB","MRNA","CEG",
        "DLTR","VRSK","ON","XEL","CPRT","CTSH","CSGP","FANG","KHC","ARM",
        "TTD","PCAR","ZS","MCHP","CCEP","SMCI","CDW","DDOG","TTWO","WBD",
        "ILMN","GFS","NXPI","CHTR","SIRI","SBUX","DASH","MTCH","LCID","ZM",
        "RIVN","OKTA","ALGN","ENPH","LULU","MDB","EBAY","JD","SWKS","BMRN"
    ]
    # Sustituciones 2024-2026:
    # ANSS (adquirida por Synopsys) → ARM (ARM Holdings, entró NDX-100 2024)
    # WBA (Walgreens, delisted 2024) → DASH (DoorDash)
    # SPLK (adquirida por Cisco 2024) → MDB (MongoDB)
    import time
    t0 = time.time()
    try:
        import yfinance as yf
        new_highs = 0
        new_lows  = 0
        total_ok  = 0
        errores   = 0

        for ticker in NDX100_TICKERS:
            try:
                col_close = ticker + "_close"
                if col_close in df.columns:
                    serie = df[col_close].dropna()
                else:
                    raw = yf.download(ticker, period="1y", progress=False, auto_adjust=True)
                    if raw.empty:
                        errores += 1
                        continue
                    if isinstance(raw.columns, pd.MultiIndex):
                        raw.columns = [c[0] for c in raw.columns]
                    serie = raw["Close"].dropna()

                if len(serie) < 252:
                    errores += 1
                    continue

                precio_actual = float(serie.iloc[-1])
                max_52w = float(serie.iloc[-252:].max())
                min_52w = float(serie.iloc[-252:].min())

                if precio_actual >= max_52w * 0.995:
                    new_highs += 1
                elif precio_actual <= min_52w * 1.005:
                    new_lows += 1
                total_ok += 1

            except Exception:
                errores += 1
                continue

        elapsed = round(time.time() - t0, 1)

        if total_ok == 0:
            return {"error": "sin_datos", "senal": "neutro", "score": 0.0}

        net_breadth = round((new_highs - new_lows) / total_ok * 100, 1)

        if net_breadth > 30:
            senal = "alcista_fuerte"
            score = 2.0
            desc  = "Amplitud NDX100 fuerte: " + str(new_highs) + " nuevos maximos vs " + str(new_lows) + " minimos"
        elif net_breadth > 10:
            senal = "alcista"
            score = 1.0
            desc  = "Amplitud NDX100 positiva: " + str(new_highs) + " maximos vs " + str(new_lows) + " minimos"
        elif net_breadth < -30:
            senal = "bajista_fuerte"
            score = -2.0
            desc  = "Amplitud NDX100 muy debil: " + str(new_highs) + " maximos vs " + str(new_lows) + " minimos - divergencia bajista"
        elif net_breadth < -10:
            senal = "bajista"
            score = -1.0
            desc  = "Amplitud NDX100 negativa: " + str(new_highs) + " maximos vs " + str(new_lows) + " minimos"
        else:
            senal = "neutro"
            score = 0.0
            desc  = "Amplitud NDX100 neutra: " + str(new_highs) + " maximos vs " + str(new_lows) + " minimos"

        log.info("  [Amplitud NDX100] " + str(new_highs) + " NH / " + str(new_lows) + " NL / "
                 + str(total_ok) + " ok / " + str(errores) + " err -> "
                 + str(net_breadth) + "% (" + senal + ") en " + str(elapsed) + "s")

        return {
            "new_highs_52w":     new_highs,
            "new_lows_52w":      new_lows,
            "total_componentes": total_ok,
            "net_breadth_pct":   net_breadth,
            "senal":             senal,
            "desc":              desc,
            "score":             score,
            "errores_descarga":  errores,
            "fuente":            "ndx100_yfinance",
            "error":             None
        }

    except Exception as e:
        log.error("  [Amplitud NDX100] Fallo total: " + str(e))
        return {"error": str(e), "senal": "neutro", "score": 0.0, "net_breadth_pct": None}


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 7 — A5  SEC Insiders: Form 4 Big Tech 90 dias
# ─────────────────────────────────────────────────────────────────────────────

def calcular_sec_insiders() -> dict:
    """
    Descarga Form 4 (insider transactions) de las 8 principales Big Tech
    via API REST publica de SEC EDGAR (sin dependencias externas).

    Flujo por empresa:
      1. GET https://data.sec.gov/submissions/CIK{cik}.json
         → lista de filings recientes con tipo, fecha y accessionNumber
      2. Para cada Form 4 en los ultimos 90 dias:
         GET https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{accn}.xml
         → parsear <transactionCode>: P=compra, S=venta
         → parsear <transactionShares> para sumar volumen real
      3. Agregar compras/ventas totales y calcular ratio

    Codigos Form 4 relevantes:
      P  = Purchase (compra en mercado abierto) — señal positiva FUERTE
      S  = Sale (venta en mercado abierto)      — señal negativa
      A  = Award/Grant de acciones              — ignorar (no es dinero propio)
      F  = Retencion para impuestos             — ignorar
      M  = Ejercicio de opciones                — ignorar
      G/D/C/W/X/Z                               — ignorar

    NOTA: Datos con retraso de hasta 2 dias habiles (normativa SEC).
    Fuente: https://data.sec.gov/submissions/ (API publica, sin autenticacion)
    """
    import requests as _req
    import xml.etree.ElementTree as ET
    import time as _time
    from datetime import datetime as dt_cls, timedelta

    BIG_TECH = {
        "AAPL":  "0000320193",
        "MSFT":  "0000789019",
        "NVDA":  "0001045810",
        "AMZN":  "0001018724",
        "META":  "0001326801",
        "GOOGL": "0001652044",
        "TSLA":  "0001318605",
        "AVGO":  "0001730168",
    }

    # User-Agent obligatorio segun politica de la SEC
    HEADERS = {
        "User-Agent":      "NQRadar nqradar@example.com",
        "Accept-Encoding": "gzip, deflate",
        "Accept":          "application/json, text/xml, */*",
    }
    TIMEOUT     = 15
    DELAY_S     = 0.12   # SEC pide max ~10 req/s; 0.12s = ~8 req/s, conservador
    fecha_limite = (dt_cls.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    compras_total  = 0   # transacciones tipo P (dinero propio)
    ventas_total   = 0   # transacciones tipo S (venta en mercado)
    shares_compras = 0   # acciones compradas (volumen)
    shares_ventas  = 0   # acciones vendidas  (volumen)
    empresas_ok    = 0
    empresas_error = []
    detalle        = []  # lista de dicts por empresa para log

    def _get_json(url):
        r = _req.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def _get_xml_text(url):
        r = _req.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r.text

    def _parse_form4_xml(xml_text, ticker):
        """
        Parsea un Form 4 XML y devuelve (compras, ventas, sh_compras, sh_ventas).
        Maneja namespaces variables del esquema SEC.
        """
        c = v = shc = shv = 0
        try:
            # El XML de Form 4 a veces tiene namespace, a veces no
            # Normalizar quitando namespace para simplicidad
            xml_clean = xml_text
            if "xmlns" in xml_text:
                import re
                xml_clean = re.sub(r'\s*xmlns[^"]*"[^"]*"', "", xml_text)
            root = ET.fromstring(xml_clean)

            # Cada transaccion esta en <nonDerivativeTransaction> o <derivativeTransaction>
            # Solo nos interesan las no-derivadas (acciones directas)
            for tx in root.findall(".//nonDerivativeTransaction"):
                code_el = tx.find(".//transactionCode")
                if code_el is None:
                    continue
                code = (code_el.text or "").strip().upper()

                shares_el = tx.find(".//transactionShares/value")
                shares = 0.0
                if shares_el is not None and shares_el.text:
                    try:
                        shares = float(shares_el.text.replace(",", ""))
                    except ValueError:
                        shares = 0.0

                if code == "P":       # compra en mercado abierto
                    c   += 1
                    shc += shares
                elif code == "S":     # venta en mercado abierto
                    v   += 1
                    shv += shares
                # A, F, M, G, D, C, W, X, Z → ignorar

        except ET.ParseError as pe:
            log.debug("  [SEC XML] " + ticker + " parse error: " + str(pe))
        return c, v, shc, shv

    def _accn_to_path(accn):
        """'0001234567-26-000123' → '000123456726000123' (sin guiones)"""
        return accn.replace("-", "")

    try:
        for ticker, cik in BIG_TECH.items():
            emp_compras = emp_ventas = emp_shc = emp_shv = 0
            emp_forms_procesados = 0
            try:
                # 1. Submissions index
                sub_url = "https://data.sec.gov/submissions/CIK" + cik + ".json"
                sub     = _get_json(sub_url)
                _time.sleep(DELAY_S)

                recent = sub.get("filings", {}).get("recent", {})
                forms  = recent.get("form",          [])
                dates  = recent.get("filingDate",    [])
                accns  = recent.get("accessionNumber", [])

                # Filtrar Form 4 dentro del periodo
                form4s = [
                    (d, a)
                    for f, d, a in zip(forms, dates, accns)
                    if f == "4" and d >= fecha_limite
                ]
                log.info("  [SEC] " + ticker + ": " + str(len(form4s)) + " Form4 en 90d")

                # 2. Descargar y parsear cada Form 4
                # Estrategia de naming (verificado empíricamente con SEC EDGAR):
                #   - Intento 1: form4.xml          → nombre estandar Big Tech (200 OK)
                #   - Intento 2: wk-form4.xml       → algunos filers Workiva
                #   - Intento 3: parsear -index.htm → fallback universal
                # El endpoint -index.json devuelve 404 para la mayoria de filers.
                cik_num = cik.lstrip("0")   # sin ceros iniciales para la ruta
                for filing_date, accn in form4s:
                    try:
                        accn_raw = _accn_to_path(accn)
                        base_url = (
                            "https://www.sec.gov/Archives/edgar/data/"
                            + cik_num + "/" + accn_raw + "/"
                        )

                        # INTENTO 1 y 2: nombres conocidos directamente
                        xml_text = None
                        for candidate in ["form4.xml", "wk-form4.xml"]:
                            try:
                                r = _req.get(
                                    base_url + candidate,
                                    headers=HEADERS, timeout=TIMEOUT
                                )
                                _time.sleep(DELAY_S)
                                if r.status_code == 200 and len(r.content) > 100:
                                    xml_text = r.text
                                    break
                            except Exception:
                                _time.sleep(DELAY_S)
                                continue

                        # INTENTO 3: parsear -index.htm para encontrar el .xml
                        if not xml_text:
                            try:
                                import re as _re
                                htm_url = base_url + accn + "-index.htm"
                                rh = _req.get(htm_url, headers=HEADERS, timeout=TIMEOUT)
                                _time.sleep(DELAY_S)
                                if rh.status_code == 200:
                                    # Buscar hrefs que terminen en .xml
                                    # y no sean schemas (.xsd) ni el -index
                                    matches = _re.findall(
                                        r'href="([^"]+\.xml)"',
                                        rh.text, _re.IGNORECASE
                                    )
                                    for m in matches:
                                        if "schema" in m.lower() or ".xsd" in m.lower():
                                            continue
                                        # m puede ser ruta relativa o absoluta
                                        xml_url = m if m.startswith("http") else base_url + m.lstrip("/").split("/")[-1]
                                        rx = _req.get(xml_url, headers=HEADERS, timeout=TIMEOUT)
                                        _time.sleep(DELAY_S)
                                        if rx.status_code == 200 and len(rx.content) > 100:
                                            xml_text = rx.text
                                            break
                            except Exception:
                                pass

                        if not xml_text:
                            log.debug("  [SEC] " + ticker + "/" + accn + ": XML no encontrado")
                            continue

                        c, v, shc, shv = _parse_form4_xml(xml_text, ticker)
                        emp_compras += c
                        emp_ventas  += v
                        emp_shc     += shc
                        emp_shv     += shv
                        emp_forms_procesados += 1

                    except Exception as e_form:
                        log.debug("  [SEC] " + ticker + "/" + accn
                                  + ": " + str(e_form))
                        _time.sleep(DELAY_S)
                        continue

                empresas_ok   += 1
                compras_total += emp_compras
                ventas_total  += emp_ventas
                shares_compras += emp_shc
                shares_ventas  += emp_shv
                detalle.append({
                    "ticker":    ticker,
                    "forms":     emp_forms_procesados,
                    "compras":   emp_compras,
                    "ventas":    emp_ventas,
                    "sh_compras": round(emp_shc),
                    "sh_ventas":  round(emp_shv),
                })
                log.info(
                    "    " + ticker + ": P=" + str(emp_compras)
                    + " S=" + str(emp_ventas)
                    + " (forms=" + str(emp_forms_procesados) + ")"
                )

            except Exception as e_emp:
                log.warning("  [SEC] " + ticker + " error: " + str(e_emp))
                empresas_error.append(ticker)
                _time.sleep(DELAY_S)
                continue

        # 3. Calcular ratio y señal
        # ratio = compras / ventas (denominador minimo 1 para evitar division por cero)
        ratio_insider = round(compras_total / max(ventas_total, 1), 2)

        # Señal basada en ratio P/S:
        #   > 0.30  → insiders comprando relativamente, ALCISTA
        #   < 0.10  → insiders solo vendiendo, BAJISTA
        #   0.10-0.30 → actividad neutral
        # (Referencia: ratio historico medio Big Tech ~0.05-0.15)
        if compras_total > 0 and ratio_insider > 0.30:
            senal = "alcista"
            desc  = (
                "Insiders Big Tech acumulando — "
                + str(compras_total) + " compras vs "
                + str(ventas_total)  + " ventas (90d)"
                + " · " + "{:,.0f}".format(shares_compras) + " acc compradas"
            )
        elif ventas_total > 0 and ratio_insider < 0.10:
            senal = "bajista"
            desc  = (
                "Insiders Big Tech vendiendo — "
                + str(ventas_total)  + " ventas vs "
                + str(compras_total) + " compras (90d)"
                + " · " + "{:,.0f}".format(shares_ventas) + " acc vendidas"
            )
        elif compras_total == 0 and ventas_total == 0:
            senal = "neutro"
            desc  = "Sin transacciones de insiders detectadas en 90d"
        else:
            senal = "neutro"
            desc  = (
                "Actividad insider neutral — "
                + str(compras_total) + " compras / "
                + str(ventas_total)  + " ventas (90d)"
            )

        if empresas_error:
            desc += " (errores: " + ",".join(empresas_error) + ")"

        log.info(
            "  [SEC Form4] " + str(empresas_ok) + "/" + str(len(BIG_TECH))
            + " empresas OK | compras=" + str(compras_total)
            + " ventas=" + str(ventas_total)
            + " ratio=" + str(ratio_insider)
            + " | " + senal.upper()
        )

        return {
            "compras_90d":    compras_total,
            "ventas_90d":     ventas_total,
            "shares_compradas": round(shares_compras),
            "shares_vendidas":  round(shares_ventas),
            "ratio":          ratio_insider,
            "empresas_ok":    empresas_ok,
            "senal":          senal,
            "desc":           desc,
            "fuente":         "sec_edgar_form4_api",
            "nota":           "Datos con retraso de hasta 2 dias habiles (normativa SEC). Solo transacciones P (compra) y S (venta) en mercado abierto.",
            "detalle":        detalle,
            "error":          None,
        }

    except Exception as e:
        log.error("  [SEC] Fallo general: " + str(e))
        return {"error": str(e), "senal": "neutro"}


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 7 — A9  CTA Trigger Levels: Donchian 20/50
# ─────────────────────────────────────────────────────────────────────────────

def calcular_cta_levels(df: "pd.DataFrame") -> dict:
    """
    Mapea los niveles donde fondos CTA (trend followers) ejecutaran
    ordenes automaticas masivas de compra o capitulacion bajista.
    Basado en rupturas de canales Donchian 20 y 50 dias sobre QQQ.
    """
    try:
        qqq_col = None
        for col in df.columns:
            if "QQQ" in col.upper() and "CLOSE" in col.upper():
                qqq_col = df[col].dropna()
                break
        if qqq_col is None or len(qqq_col) < 55:
            return {"error": "datos_insuficientes", "senal_cta": "neutro"}

        precio      = float(qqq_col.iloc[-1])
        prev_precio = float(qqq_col.iloc[-2])

        don20_high = float(qqq_col.iloc[-22:-1].max())
        don20_low  = float(qqq_col.iloc[-22:-1].min())
        don50_high = float(qqq_col.iloc[-52:-1].max())
        don50_low  = float(qqq_col.iloc[-52:-1].min())

        dist_d20h = round((don20_high - precio) / precio * 100, 2)
        dist_d20l = round((don20_low  - precio) / precio * 100, 2)
        dist_d50h = round((don50_high - precio) / precio * 100, 2)
        dist_d50l = round((don50_low  - precio) / precio * 100, 2)

        senal_cta = "neutro"
        desc_cta  = "Precio dentro de canales Donchian - CTAs en espera"

        if precio >= don20_high and prev_precio < don20_high:
            senal_cta = "compra_activada_d20"
            desc_cta  = "CTA COMPRA D20 activada - QQQ rompe " + str(round(don20_high, 2))
        elif precio >= don50_high and prev_precio < don50_high:
            senal_cta = "compra_activada_d50"
            desc_cta  = "CTA COMPRA D50 activada - QQQ rompe " + str(round(don50_high, 2)) + " (senal fuerte)"
        elif precio <= don20_low and prev_precio > don20_low:
            senal_cta = "capitulacion_d20"
            desc_cta  = "CTA CAPITULACION D20 - QQQ rompe " + str(round(don20_low, 2))
        elif precio <= don50_low and prev_precio > don50_low:
            senal_cta = "capitulacion_d50"
            desc_cta  = "CTA CAPITULACION D50 - QQQ rompe " + str(round(don50_low, 2)) + " (senal fuerte)"
        elif abs(dist_d20h) < 0.5:
            senal_cta = "cerca_ruptura_alcista"
            desc_cta  = "QQQ a " + str(abs(dist_d20h)) + "% del gatillo CTA alcista D20"
        elif abs(dist_d20l) < 0.5:
            senal_cta = "cerca_capitulacion"
            desc_cta  = "QQQ a " + str(abs(dist_d20l)) + "% del gatillo CTA bajista D20"

        log.info("  [CTA] D20: " + str(round(don20_low, 2)) + "/" + str(round(don20_high, 2))
                 + " | D50: " + str(round(don50_low, 2)) + "/" + str(round(don50_high, 2))
                 + " | Senal=" + senal_cta)

        return {
            "don20_high":          round(don20_high, 2),
            "don20_low":           round(don20_low, 2),
            "don50_high":          round(don50_high, 2),
            "don50_low":           round(don50_low, 2),
            "precio_qqq":          round(precio, 2),
            "dist_don20_high_pct": dist_d20h,
            "dist_don20_low_pct":  dist_d20l,
            "dist_don50_high_pct": dist_d50h,
            "dist_don50_low_pct":  dist_d50l,
            "senal_cta":           senal_cta,
            "desc":                desc_cta,
            "error":               None
        }
    except Exception as e:
        log.error("  [CTA] Fallo: " + str(e))
        return {"error": str(e), "senal_cta": "neutro"}




def cargar_o_inicializar_historico(forzar_init: bool = False) -> pd.DataFrame:
    if not HISTORICO_PATH.exists() or forzar_init:
        log.info("=" * 60)
        log.info("FASE INIT — Descarga histórica completa desde 2000")
        log.info("(Esto puede tardar 2-5 minutos)")
        log.info("=" * 60)
        return _init_historico()
    else:
        log.info("FASE DELTA — Carga incremental (solo datos nuevos)")
        return _delta_historico()


def _init_historico() -> pd.DataFrame:
    dfs = {}
    for nombre, ticker in SIMBOLOS.items():
        log.info(f"Descargando {nombre} ({ticker})...")
        df = descargar_datos(ticker, FECHA_INICIO)
        if not df.empty:
            df.columns = [f"{nombre}_{c}" for c in df.columns]
            dfs[nombre] = df

    if not dfs:
        log.error("No se pudo descargar ningún símbolo.")
        sys.exit(1)

    df_maestro = None
    for nombre, df in dfs.items():
        df_maestro = df if df_maestro is None else df_maestro.join(df, how="outer")

    df_maestro = df_maestro.sort_index()
    df_maestro.to_csv(HISTORICO_PATH)
    log.info(f"✅ historico_maestro.csv: {len(df_maestro)} filas, {len(df_maestro.columns)} cols")
    return df_maestro


def _delta_historico() -> pd.DataFrame:
    log.info(f"  Leyendo {HISTORICO_PATH.name}...")
    df_maestro = pd.read_csv(HISTORICO_PATH, index_col="fecha", parse_dates=True)
    df_maestro.index = pd.to_datetime(df_maestro.index).normalize()

    ultima_fecha = df_maestro.index.max()
    hoy = pd.Timestamp(date.today())

    if ultima_fecha >= hoy - timedelta(days=1):
        log.info(f"  Datos al día ({ultima_fecha.date()}). No hay delta.")
        return df_maestro

    inicio_delta = (ultima_fecha + timedelta(days=1)).strftime("%Y-%m-%d")
    log.info(f"  Descargando delta desde {inicio_delta}...")

    dfs_nuevos = {}
    for nombre, ticker in SIMBOLOS.items():
        df_nuevo = descargar_datos(ticker, inicio_delta)
        if not df_nuevo.empty:
            df_nuevo.columns = [f"{nombre}_{c}" for c in df_nuevo.columns]
            dfs_nuevos[nombre] = df_nuevo

    if not dfs_nuevos:
        log.info("  No hay datos nuevos (mercado cerrado o fin de semana).")
        return df_maestro

    df_delta = None
    for nombre, df in dfs_nuevos.items():
        df_delta = df if df_delta is None else df_delta.join(df, how="outer")

    df_maestro = pd.concat([df_maestro, df_delta]).sort_index()
    df_maestro = df_maestro[~df_maestro.index.duplicated(keep="last")]
    df_maestro.to_csv(HISTORICO_PATH)
    log.info(f"  ✅ {len(df_delta)} filas nuevas. Total: {len(df_maestro)}")
    return df_maestro


# ─────────────────────────────────────────────────────────────────────────────
#  MÓDULO TÉCNICO — INDICADORES (sin cambios respecto Fase 1)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_ema(series: pd.Series, periodo: int) -> pd.Series:
    return series.ewm(span=periodo, adjust=False).mean()

def calcular_sma(series: pd.Series, periodo: int) -> pd.Series:
    return series.rolling(window=periodo).mean()

def calcular_rsi(series: pd.Series, periodo: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=periodo - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=periodo - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calcular_macd(series: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    ema_fast = calcular_ema(series, fast)
    ema_slow = calcular_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calcular_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({"line": macd_line, "signal": signal_line, "hist": histogram})

def calcular_bollinger(series: pd.Series, periodo=20, std_factor=2) -> pd.DataFrame:
    sma = series.rolling(window=periodo).mean()
    std = series.rolling(window=periodo).std()
    upper = sma + std_factor * std
    lower = sma - std_factor * std
    width = ((upper - lower) / sma * 100).round(2)
    pct_b = ((series - lower) / (upper - lower) * 100).round(2)
    return pd.DataFrame({"upper": upper, "mid": sma, "lower": lower, "width": width, "pct": pct_b})

def calcular_atr(high: pd.Series, low: pd.Series, close: pd.Series, periodo=14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=periodo).mean()

def calcular_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()

def calcular_stochastico(high: pd.Series, low: pd.Series, close: pd.Series,
                          k_period=14, d_period=3) -> pd.DataFrame:
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    k = ((close - lowest_low) / denom * 100)
    d = k.rolling(window=d_period).mean()
    return pd.DataFrame({"k": k, "d": d})

def calcular_vol_relativo(volume: pd.Series, periodo_short=5, periodo_long=20) -> pd.Series:
    vol_short = volume.rolling(window=periodo_short).mean()
    vol_long = volume.rolling(window=periodo_long).mean()
    return (vol_short / vol_long.replace(0, np.nan)).round(3)

def calcular_roc(series: pd.Series, periodos: int) -> pd.Series:
    return ((series / series.shift(periodos) - 1) * 100).round(3)


def calcular_tecnicos(df_maestro: pd.DataFrame, simbolo: str = "NDX") -> dict:
    prefix = simbolo + "_"
    cols_necesarias = ["close", "high", "low", "volume"]

    for col in cols_necesarias:
        full_col = prefix + col
        if full_col not in df_maestro.columns:
            log.warning(f"  Columna {full_col} no encontrada")
            if col in ["high", "low"]:
                df_maestro[full_col] = df_maestro.get(prefix + "close", pd.Series(dtype=float))
            elif col == "volume":
                df_maestro[full_col] = 0

    cl = df_maestro[prefix + "close"].dropna()
    hi = df_maestro.get(prefix + "high", cl).reindex(cl.index).fillna(cl)
    lo = df_maestro.get(prefix + "low", cl).reindex(cl.index).fillna(cl)
    vo = df_maestro.get(prefix + "volume", pd.Series(0, index=cl.index)).reindex(cl.index).fillna(0)

    if len(cl) < 50:
        log.warning(f"  Datos insuficientes para {simbolo}: {len(cl)} velas")
        return {}

    rsi14 = calcular_rsi(cl, 14)
    rsi5  = calcular_rsi(cl, 5)
    macd  = calcular_macd(cl)
    bb    = calcular_bollinger(cl)
    atr14 = calcular_atr(hi, lo, cl, 14)
    stoch = calcular_stochastico(hi, lo, cl)
    obv   = calcular_obv(cl, vo)
    vol_r = calcular_vol_relativo(vo)

    ema8   = calcular_ema(cl, 8)
    ema13  = calcular_ema(cl, 13)
    ema21  = calcular_ema(cl, 21)
    ema50  = calcular_ema(cl, 50)
    ema100 = calcular_ema(cl, 100)
    ema200 = calcular_ema(cl, 200)
    sma20  = calcular_sma(cl, 20)
    sma50  = calcular_sma(cl, 50)
    sma200 = calcular_sma(cl, 200)

    roc5  = calcular_roc(cl, 5)
    roc10 = calcular_roc(cl, 10)
    roc20 = calcular_roc(cl, 20)

    def last(s):
        return round(float(s.iloc[-1]), 4) if len(s) > 0 and pd.notna(s.iloc[-1]) else None

    precio_actual = last(cl)

    diario = {
        "precio":    precio_actual,
        "rsi14":     last(rsi14),
        "rsi5":      last(rsi5),
        "macd": {
            "line":   last(macd["line"]),
            "signal": last(macd["signal"]),
            "hist":   last(macd["hist"]),
        },
        "stoch": {
            "k": round(last(stoch["k"]) or 50, 2),
            "d": round(last(stoch["d"]) or 50, 2),
        },
        "bb": {
            "upper": last(bb["upper"]),
            "mid":   last(bb["mid"]),
            "lower": last(bb["lower"]),
            "width": last(bb["width"]),
            "pct":   last(bb["pct"]),
        },
        "ema8":    last(ema8),
        "ema13":   last(ema13),
        "ema21":   last(ema21),
        "ema50":   last(ema50),
        "ema100":  last(ema100),
        "ema200":  last(ema200),
        "sma20":   last(sma20),
        "sma50":   last(sma50),
        "sma200":  last(sma200),
        "atr14":   last(atr14),
        "obv":     last(obv),
        "roc5":    last(roc5),
        "roc10":   last(roc10),
        "roc20":   last(roc20),
        "volRatio5": last(vol_r),
    }

    cl_w  = cl.resample("W").last().dropna()
    hi_w  = hi.resample("W").max().reindex(cl_w.index).fillna(cl_w)
    lo_w  = lo.resample("W").min().reindex(cl_w.index).fillna(cl_w)

    semanal = None
    if len(cl_w) >= 26:
        rsi14_w = calcular_rsi(cl_w, 14)
        macd_w  = calcular_macd(cl_w)
        bb_w    = calcular_bollinger(cl_w)
        stoch_w = calcular_stochastico(hi_w, lo_w, cl_w) if len(cl_w) >= 17 else None
        ema13_w = calcular_ema(cl_w, 13)
        ema26_w = calcular_ema(cl_w, 26)
        ema52_w = calcular_ema(cl_w, 52)
        roc4_w  = calcular_roc(cl_w, 4)
        roc8_w  = calcular_roc(cl_w, 8)
        semanal = {
            "rsi14":  last(rsi14_w),
            "macd": {
                "line":   last(macd_w["line"]),
                "signal": last(macd_w["signal"]),
                "hist":   last(macd_w["hist"]),
            },
            "stoch": {"k": round(last(stoch_w["k"]) or 50, 2), "d": round(last(stoch_w["d"]) or 50, 2)} if stoch_w is not None else None,
            "bb": {
                "upper": last(bb_w["upper"]),
                "mid":   last(bb_w["mid"]),
                "lower": last(bb_w["lower"]),
                "width": last(bb_w["width"]),
                "pct":   last(bb_w["pct"]),
            },
            "ema13": last(ema13_w),
            "ema26": last(ema26_w),
            "ema52": last(ema52_w),
            "roc4":  last(roc4_w),
            "roc8":  last(roc8_w),
        }

    cl_m  = cl.resample("ME").last().dropna()
    hi_m  = hi.resample("ME").max().reindex(cl_m.index).fillna(cl_m)
    lo_m  = lo.resample("ME").min().reindex(cl_m.index).fillna(cl_m)

    mensual = None
    if len(cl_m) >= 14:
        rsi14_m = calcular_rsi(cl_m, 14)
        ema5_m  = calcular_ema(cl_m, 5)
        ema10_m = calcular_ema(cl_m, 10)
        ema20_m = calcular_ema(cl_m, 20)
        roc3_m  = calcular_roc(cl_m, 3)
        mensual = {
            "rsi14": last(rsi14_m),
            "ema5":  last(ema5_m),
            "ema10": last(ema10_m),
            "ema20": last(ema20_m),
            "roc3":  last(roc3_m),
        }

    return {"label": simbolo, "d": diario, "w": semanal, "m": mensual}


# ─────────────────────────────────────────────────────────────────────────────
#  VIX TERM STRUCTURE
# ─────────────────────────────────────────────────────────────────────────────

def calcular_vix_ts(df_maestro: pd.DataFrame) -> dict:
    def last_val(col):
        if col in df_maestro.columns:
            s = df_maestro[col].dropna()
            return round(float(s.iloc[-1]), 2) if len(s) > 0 else None
        return None

    vix_spot = last_val("VIX_close")
    vix3m    = last_val("VIX3M_close")

    spread1     = round(vix3m - vix_spot, 2) if vix_spot and vix3m else None
    spread1_pct = round(spread1 / vix_spot * 100, 1) if spread1 and vix_spot else None
    back        = spread1 < 0 if spread1 is not None else None

    vix_hist = df_maestro["VIX_close"].dropna() if "VIX_close" in df_maestro.columns else pd.Series()
    vix_pct  = None
    if len(vix_hist) > 20 and vix_spot:
        vix_pct = int(round((vix_hist <= vix_spot).sum() / len(vix_hist) * 100))

    if back:
        senal = "alcista"
        desc  = "VIX backwardation — estrés agudo, rebote probable 2-5d"
    elif spread1_pct and spread1_pct > 20:
        senal = "bajista_fuerte"
        desc  = "Contango extremo — complacencia máxima, corrección probable"
    elif spread1_pct and spread1_pct > 10:
        senal = "bajista"
        desc  = "Contango elevado — complacencia, vigilar"
    else:
        senal = "neutro"
        desc  = "Term structure normal"

    return {
        "spot":          vix_spot,
        "vix3m":         vix3m,
        "spread1":       spread1,
        "spread1Pct":    spread1_pct,
        "backwardation": back,
        "vixPercentil":  vix_pct,
        "señal":         senal,
        "desc":          desc,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  MÓDULO: parsear_vix_ts_txt — Lee VIX.txt descargado de Cboe VIX Futures
#  Ruta esperada: BASE_DIR / "VIX.txt"
#  Formato: tabla TSV con columnas Symbol / Expiration / Last Price /
#           Change / High / Low / Settlement / Volume
#  Estrategia: enriquece el resultado de calcular_vix_ts con datos reales
#  de la curva de futuros (front month, segundo mes, pendiente, contango/bk)
# ─────────────────────────────────────────────────────────────────────────────

def parsear_vix_ts_txt(base_dir: Path = None) -> dict:
    """
    Lee VIX.txt guardado en nq-proxy y extrae la curva de futuros VIX.

    Datos que extrae:
      - VIX spot (línea "VIX\\t-\\t21.57\\t...")
      - Front month (primer contrato con precio real, no semanal/mini)
      - Second month
      - Todos los contratos mensuales estándar (VX/XX)
      - Spread spot vs front → contango o backwardation
      - Pendiente de la curva (slope 1M→3M)
      - Señal interpretativa: alcista / neutro / bajista / bajista_fuerte

    El precio preferido es Last Price; si es "-" se usa Settlement como fallback
    (ocurre en fin de semana — Settlement es el precio de cierre del viernes).

    Devuelve None si el archivo no existe o no se puede parsear.
    """
    if base_dir is None:
        base_dir = BASE_DIR

    candidatos = [base_dir / "VIX.txt", base_dir / "vix.txt", base_dir / "VIX.TXT"]
    ruta = next((p for p in candidatos if p.exists()), None)
    if ruta is None:
        return None

    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        lineas = texto.splitlines()

        vix_spot   = None
        futuros    = []  # lista de dicts {symbol, expiry, precio, settlement, dte}

        hoy = datetime.now().date()

        for linea in lineas:
            partes = [p.strip() for p in linea.strip().split("\t")]
            if len(partes) < 7:
                continue

            simbolo = partes[0]
            expiry_str = partes[1]
            last_str   = partes[2]
            settlement_str = partes[6] if len(partes) > 6 else "-"

            def _to_float(s):
                try:
                    v = float(s.replace(",", "."))
                    return v if v > 0 else None
                except (ValueError, TypeError):
                    return None

            # ── VIX spot ────────────────────────────────────────────────────
            if simbolo == "VIX" and expiry_str == "-":
                last = _to_float(last_str)
                sett = _to_float(settlement_str)
                vix_spot = last or sett
                continue

            # ── Futuros VIX: solo contratos con fecha de vencimiento ────────
            # Aceptar: VX/M6, VX/N6, VX/Q6 ... (contratos mensuales estándar)
            # Aceptar también: VX23/M6, VX25/M6 (weeklys) pero con flag is_weekly
            if not (simbolo.startswith("VX") and "/" in simbolo):
                continue
            if expiry_str == "-" or not expiry_str:
                continue

            try:
                from datetime import datetime as dt_cls
                expiry_date = dt_cls.strptime(expiry_str, "%m/%d/%Y").date()
            except ValueError:
                continue

            dte = (expiry_date - hoy).days
            if dte < 0:
                continue  # vencido

            last  = _to_float(last_str)
            sett  = _to_float(settlement_str)
            precio = last or sett  # usar settlement si no hay last (fin de semana)

            if precio is None:
                continue

            # Distinguir contratos semanales (tienen número: VX23/M6) de mensuales (VX/M6)
            import re as _re
            is_weekly = bool(_re.match(r"VX\d+/", simbolo))

            futuros.append({
                "symbol":     simbolo,
                "expiry":     expiry_str,
                "expiry_date": expiry_date.isoformat(),
                "precio":     round(precio, 4),
                "last":       last,
                "settlement": sett,
                "dte":        dte,
                "is_weekly":  is_weekly,
                "using_settlement": last is None,
            })

        if not futuros:
            log.warning("  [VIX-TXT] Archivo encontrado pero sin futuros parseables")
            return None

        # Ordenar por DTE
        futuros.sort(key=lambda x: x["dte"])

        # Contratos mensuales (excluir weeklys para la curva principal)
        mensuales = [f for f in futuros if not f["is_weekly"]]

        # Front month y second month (de contratos mensuales)
        front  = mensuales[0] if len(mensuales) > 0 else futuros[0]
        second = mensuales[1] if len(mensuales) > 1 else (futuros[1] if len(futuros) > 1 else None)
        third  = mensuales[2] if len(mensuales) > 2 else None

        front_precio  = front["precio"]
        second_precio = second["precio"] if second else None

        # ── Cálculos de estructura ────────────────────────────────────────────

        # Spread spot-front (contango = spot < front → positivo)
        spread_sf  = round(front_precio - vix_spot, 2) if vix_spot else None
        spread_pct = round(spread_sf / vix_spot * 100, 1) if (spread_sf is not None and vix_spot) else None
        backwardation = spread_sf < 0 if spread_sf is not None else None

        # Pendiente de la curva: (second - front) / dte_entre_ellos * 30
        # Normalizada a "puntos por mes" para comparar entre periodos
        slope_1m2m = None
        if second and second_precio and front_precio:
            delta_dte = second["dte"] - front["dte"]
            if delta_dte > 0:
                slope_1m2m = round((second_precio - front_precio) / delta_dte * 30, 3)

        # Contango score: clasificación de la curva
        # Usamos spread spot-front (el más importante para señal 2-5D)
        if backwardation:
            senal = "alcista"
            desc  = (f"VIX backwardation — spot={vix_spot} > front={front_precio} "
                     f"(spread={spread_sf:+.2f}) — estrés agudo, rebote probable 2-5d")
        elif spread_pct and spread_pct > 20:
            senal = "bajista_fuerte"
            desc  = (f"Contango extremo — spot={vix_spot} front={front_precio} "
                     f"({spread_pct:+.1f}%) — complacencia máxima, corrección probable")
        elif spread_pct and spread_pct > 10:
            senal = "bajista"
            desc  = (f"Contango elevado — spot={vix_spot} front={front_precio} "
                     f"({spread_pct:+.1f}%) — complacencia, vigilar")
        elif spread_pct and spread_pct < -5:
            senal = "alcista_fuerte"
            desc  = (f"Backwardation pronunciada — spot={vix_spot} front={front_precio} "
                     f"({spread_pct:+.1f}%) — pánico extremo, rebote inminente")
        else:
            senal = "neutro"
            desc  = (f"Term structure normal — spot={vix_spot} front={front_precio} "
                     f"({spread_pct:+.1f}%)" if spread_pct else "Term structure normal")

        result = {
            # Campos compatibles con calcular_vix_ts (mismo formato)
            "spot":          vix_spot,
            "vix3m":         third["precio"] if third else second_precio,
            "spread1":       spread_sf,
            "spread1Pct":    spread_pct,
            "backwardation": backwardation,
            "vixPercentil":  None,  # no disponible desde TXT (requiere histórico)
            "señal":         senal,
            "desc":          desc,
            # Campos extra (enriquecimiento respecto a calcular_vix_ts)
            "front_month":   front,
            "second_month":  second,
            "slope_1m2m":    slope_1m2m,
            "curva":         futuros[:8],  # máx 8 contratos para el frontend
            "n_contratos":   len(futuros),
            "fuente":        "vix_txt_manual",
            "usando_settlement": any(f["using_settlement"] for f in futuros[:3]),
        }

        using_sett = any(f["using_settlement"] for f in futuros[:2])
        log.info(
            f"  [VIX-TXT] OK — spot={vix_spot} | front={front['symbol']}={front_precio} "
            f"| spread={spread_sf:+.2f} ({spread_pct:+.1f}%) | {senal.upper()} "
            f"| {len(futuros)} contratos" + (" [usando settlement]" if using_sett else "")
        )
        return result

    except Exception as e:
        log.warning(f"  [VIX-TXT] Error parseando VIX.txt: {e}")
        import traceback
        log.warning(traceback.format_exc())
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  DETECTORES DE GIRO
# ─────────────────────────────────────────────────────────────────────────────

def detectar_giro(df_maestro: pd.DataFrame, tecnicos: dict) -> dict:
    cl_raw = df_maestro.get("NDX_close", df_maestro.get("QQQ_close", pd.Series())).dropna()
    if len(cl_raw) < 30:
        return {"señalGlobal": "neutro"}

    cl = cl_raw.copy()
    rsi_series = calcular_rsi(cl, 14)

    div_alcista = False
    div_bajista = False
    n = len(cl)
    for i in range(3, min(20, n)):
        pa, pb = cl.iloc[-1], cl.iloc[-1 - i]
        ra, rb = rsi_series.iloc[-1], rsi_series.iloc[-1 - i]
        if pd.notna(ra) and pd.notna(rb):
            if pa < pb and ra > rb and ra < 45:
                div_alcista = True
            if pa > pb and ra < rb and ra > 60:
                div_bajista = True

    cl_w = cl.resample("W").last().dropna()
    rsi_w = calcular_rsi(cl_w, 14)
    wn = len(cl_w)
    wdiv_alcista = False
    wdiv_bajista = False
    for i in range(2, min(10, wn)):
        pa, pb = cl_w.iloc[-1], cl_w.iloc[-1 - i]
        ra, rb = rsi_w.iloc[-1], rsi_w.iloc[-1 - i]
        if pd.notna(ra) and pd.notna(rb):
            if pa < pb and ra > rb and ra < 45:
                wdiv_alcista = True
            if pa > pb and ra < rb and ra > 60:
                wdiv_bajista = True

    bb_data  = tecnicos.get("d", {}).get("bb", {})
    bb_senal = "neutro"
    bb_pct   = bb_data.get("pct")
    if bb_pct is not None:
        if bb_pct >= 95:
            bb_senal = "techo"
        elif bb_pct <= 5:
            bb_senal = "suelo"

    cl_vals = cl.values
    dias = 0
    direccion = "lateral"
    for i in range(n - 1, max(n - 16, 0), -1):
        if i >= len(cl_vals):
            break
        sube = cl_vals[i] > cl_vals[i - 1]
        baja = cl_vals[i] < cl_vals[i - 1]
        if i == n - 1:
            direccion = "subiendo" if sube else ("bajando" if baja else "lateral")
        if (direccion == "subiendo" and sube) or (direccion == "bajando" and baja):
            dias += 1
        else:
            break

    if dias >= 7 and direccion == "subiendo":
        dc_senal = "agotamiento"
    elif dias >= 5 and direccion == "bajando":
        dc_senal = "rebote"
    elif dias >= 5 and direccion == "subiendo":
        dc_senal = "vigilar_techo"
    else:
        dc_senal = "normal"

    if div_bajista or bb_senal == "techo" or (dias >= 7 and direccion == "subiendo"):
        senal_global = "techo"
    elif div_alcista or bb_senal == "suelo" or (dias >= 5 and direccion == "bajando"):
        senal_global = "suelo"
    else:
        senal_global = "neutro"

    return {
        "d": {
            "divAlcista": div_alcista,
            "divBajista": div_bajista,
            "fiabilidad": "alta" if div_bajista and dias >= 5 else ("media" if div_bajista or div_alcista else "sin_div"),
        },
        "w": {"divAlcista": wdiv_alcista, "divBajista": wdiv_bajista},
        "bb": {"señal": bb_senal, "pct": bb_pct, "width": bb_data.get("width")},
        "diasConsec": {"dias": dias, "dir": direccion, "señal": dc_senal},
        "señalGlobal": senal_global,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  FLUJOS ETF
# ─────────────────────────────────────────────────────────────────────────────

def calcular_flujos(df_maestro: pd.DataFrame) -> dict:
    etfs = {"qqq": "QQQ", "spy": "SPY", "tlt": "TLT",
            "hyg": "HYG", "gld": "GLD", "eem": "EEM", "iwm": "IWM"}

    def flow_etf(nombre, simbolo):
        col = f"{simbolo}_close"
        vcol = f"{simbolo}_volume"
        if col not in df_maestro.columns:
            return {"name": nombre.upper(), "error": "sin datos"}
        cl = df_maestro[col].dropna()
        vo = df_maestro.get(vcol, pd.Series(0, index=cl.index)).reindex(cl.index).fillna(0)
        n = len(cl)
        if n < 6:
            return {"name": nombre.upper(), "retorno5d": None}

        r5d  = round((cl.iloc[-1] / cl.iloc[-6]  - 1) * 100, 2) if n >= 6  else None
        r10d = round((cl.iloc[-1] / cl.iloc[-11] - 1) * 100, 2) if n >= 11 else None
        r20d = round((cl.iloc[-1] / cl.iloc[-21] - 1) * 100, 2) if n >= 21 else None

        vol_media  = float(vo.mean()) if len(vo) > 0 else 1
        vol_5d     = float(vo.iloc[-5:].mean()) if len(vo) >= 5 else vol_media
        vol_ratio  = round(vol_5d / vol_media, 2) if vol_media > 0 else None

        if r5d is not None and vol_ratio is not None:
            if r5d > 1 and vol_ratio > 1.1:    senal = "entradas"
            elif r5d < -1 and vol_ratio > 1.1:  senal = "salidas"
            elif r5d > 2:                        senal = "entradas_mod"
            elif r5d < -2:                       senal = "salidas_mod"
            else:                                senal = "neutro"
        else:
            senal = "neutro"

        return {"name": nombre.upper(), "retorno5d": r5d, "retorno10d": r10d,
                "retorno20d": r20d, "volRatio": vol_ratio, "señal": senal}

    resultado = {k: flow_etf(k, v) for k, v in etfs.items()}

    qr = resultado["qqq"].get("retorno5d") or 0
    tr = resultado["tlt"].get("retorno5d") or 0
    hr = resultado["hyg"].get("retorno5d") or 0

    if qr > 0.5 and hr > 0 and tr < 0:
        modo = "risk_on"
    elif qr < -0.5 and hr < 0 and tr > 0:
        modo = "risk_off"
    elif qr < -1 and tr > 1:
        modo = "vuelo_calidad"
    else:
        modo = "neutro"

    resultado["modo"] = modo
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
#  ZONAS DE LIQUIDEZ
# ─────────────────────────────────────────────────────────────────────────────

def calcular_liquidez(df_maestro: pd.DataFrame, tecnicos: dict) -> dict:
    col_cl = "NDX_close"
    col_hi = "NDX_high"
    col_lo = "NDX_low"
    if col_cl not in df_maestro.columns:
        col_cl = "QQQ_close"
        col_hi = "QQQ_high"
        col_lo = "QQQ_low"

    cl = df_maestro[col_cl].dropna()
    hi = df_maestro.get(col_hi, cl).reindex(cl.index).fillna(cl)
    lo = df_maestro.get(col_lo, cl).reindex(cl.index).fillna(cl)

    precio = float(cl.iloc[-1])
    atr14v = tecnicos.get("d", {}).get("atr14") or float(calcular_atr(hi, lo, cl).iloc[-1])

    n = len(cl)
    swing_highs, swing_lows = [], []
    cl_vals = cl.values
    hi_vals = hi.values
    lo_vals = lo.values

    for i in range(3, n - 3):
        if all(hi_vals[i] > hi_vals[j] for j in list(range(i-3, i)) + list(range(i+1, i+4))):
            swing_highs.append({"v": float(hi_vals[i]), "i": i, "reciente": i >= n - 20})
        if all(lo_vals[i] < lo_vals[j] for j in list(range(i-3, i)) + list(range(i+1, i+4))):
            swing_lows.append({"v": float(lo_vals[i]), "i": i, "reciente": i >= n - 20})

    def agrupar(arr):
        grupos = []
        for s in arr:
            found = next((g for g in grupos if abs(g["v"] - s["v"]) / g["v"] < 0.003), None)
            if found:
                found["cnt"] += 1
                found["v"]    = (found["v"] * (found["cnt"] - 1) + s["v"]) / found["cnt"]
                found["rec"]  = found["rec"] or s["reciente"]
            else:
                grupos.append({"v": s["v"], "cnt": 1, "rec": s["reciente"]})
        return sorted(grupos, key=lambda x: (-x["cnt"], -x["rec"]))[:6]

    # Filtro de proximidad: max 20% para resistencias, max 25% para soportes
    MAX_DIST_RES = 0.20
    MAX_DIST_SUP = 0.25

    zonas_r = [{"nivel": round(g["v"], 2), "igualdad": g["cnt"] >= 2, "cnt": g["cnt"],
                "reciente": g["rec"], "distPct": round((g["v"] - precio) / precio * 100, 2)}
               for g in agrupar([s for s in swing_highs
                                 if s["v"] > precio
                                 and (s["v"] - precio) / precio < MAX_DIST_RES])]
    zonas_s = [{"nivel": round(g["v"], 2), "igualdad": g["cnt"] >= 2, "cnt": g["cnt"],
                "reciente": g["rec"], "distPct": round((g["v"] - precio) / precio * 100, 2)}
               for g in agrupar([s for s in swing_lows
                                 if s["v"] < precio
                                 and (precio - s["v"]) / precio < MAX_DIST_SUP])]

    est = {
        "d2": {"sup": round(precio - atr14v * 0.5, 2), "res": round(precio + atr14v * 0.5, 2)},
        "d5": {"sup": round(precio - atr14v * 1.2, 2), "res": round(precio + atr14v * 1.2, 2)},
        "w1": {"sup": round(precio - atr14v * 2.0, 2), "res": round(precio + atr14v * 2.0, 2)},
        "w2": {"sup": round(precio - atr14v * 3.0, 2), "res": round(precio + atr14v * 3.0, 2)},
        "w3": {"sup": round(precio - atr14v * 4.0, 2), "res": round(precio + atr14v * 4.0, 2)},
        "w4": {"sup": round(precio - atr14v * 5.0, 2), "res": round(precio + atr14v * 5.0, 2)},
    }

    return {
        "precio": precio,
        "atr14": round(atr14v, 2),
        "zonasResistencia": zonas_r,
        "zonasSoporte": zonas_s,
        "rangosPorHorizonte": est,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  PRECIOS ACTUALES
# ─────────────────────────────────────────────────────────────────────────────

def extraer_precios(df_maestro: pd.DataFrame) -> dict:
    def lv(col):
        if col in df_maestro.columns:
            s = df_maestro[col].dropna()
            return round(float(s.iloc[-1]), 4) if len(s) > 0 else None
        return None

    return {
        "ndx": lv("NDX_close"),
        "qqq": lv("QQQ_close"),
        "spy": lv("SPY_close"),
        "vix": lv("VIX_close"),
        "vxn": lv("VXN_close"),
        "dxy": lv("DXY_close"),
        "tnx": lv("TNX_close"),
        "tlt": lv("TLT_close"),
        "gld": lv("GLD_close"),
        "oro": lv("GC_close"),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  ██████╗  MÓDULO FASE 2 — MACRO FRED COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

def calcular_macro_fred(df_maestro: pd.DataFrame, precios: dict) -> dict:
    """
    Módulo Fase 2: Macro profundo vía FRED API + correlaciones desde histórico.

    Calcula:
      1. Liquidez Neta del Sistema (WALCL - WTREGEN - RRPONTSYD)
      2. Tipos reales DFII10 y lógica oro/inflación
      3. Curva de tipos completa con señales de inversión
      4. Condiciones financieras (NFCI, HY Spread)
      5. DXY correlación móvil 30/90 días con QQQ
      6. Score macro real integrado
    """
    log.info("  Obteniendo datos FRED (últimos valores)...")

    # ── 1. FETCH PARALELO de los últimos valores de cada serie ──────────────
    series_a_consultar = [
        "WALCL", "WTREGEN", "RRPONTSYD",
        "FEDFUNDS", "SOFR",
        "DFII10", "T5YIE", "T10YIE", "T5YIFR",
        "BAMLH0A0HYM2", "NFCI",
        "T10Y2Y", "T10Y3M",
        "DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30",
        "WLCFLPCL",   # Fase 7: ventanilla descuento Fed
    ]

    fred_vals = {}
    for sid in series_a_consultar:
        fred_vals[sid] = fred_con_fallback(sid, df_maestro, sid.lower() + "_close", n=3)

    # CPI YoY — necesita n=14 para calcular variacion anual aproximada (Fase 7)
    cpi_12m = descargar_fred_ultimo("CPIAUCSL", n=14)
    cpi_yoy = None
    if cpi_12m and cpi_12m.get("prev") and cpi_12m["prev"]:
        try:
            cpi_yoy = round((cpi_12m["v"] / cpi_12m["prev"] - 1) * 12 * 100, 2)
        except Exception:
            cpi_yoy = None
    log.info("  CPI YoY aprox: " + str(cpi_yoy) + "%")

    # ── 2. LIQUIDEZ NETA DEL SISTEMA ─────────────────────────────────────────
    walcl_raw    = fred_vals.get("WALCL")
    wtregen_raw  = fred_vals.get("WTREGEN")
    rrponts_raw  = fred_vals.get("RRPONTSYD")

    liquidez_neta = None
    liquidez_neta_trend = None
    if walcl_raw and wtregen_raw and rrponts_raw:
        # FRED da WALCL en millones, WTREGEN y RRPONTSYD en millones
        lv = walcl_raw["v"] - wtregen_raw["v"] - rrponts_raw["v"]
        liquidez_neta = round(lv, 0)
        # Trend: comparar con previos si disponibles
        if walcl_raw.get("prev") and wtregen_raw.get("prev") and rrponts_raw.get("prev"):
            lv_prev = walcl_raw["prev"] - wtregen_raw["prev"] - rrponts_raw["prev"]
            liquidez_neta_trend = "up" if lv > lv_prev else "down"
        log.info(f"  Liquidez Neta Fed: {liquidez_neta:,.0f}M USD ({liquidez_neta_trend})")

    # ── 3. TIPOS REALES, INFLACIÓN Y LÓGICA ORO ──────────────────────────────
    tipo_real_10y = fred_vals.get("DFII10")
    t5yie         = fred_vals.get("T5YIE")
    t10yie        = fred_vals.get("T10YIE")
    t5y5y         = fred_vals.get("T5YIFR")

    tipo_real_v = tipo_real_10y["v"] if tipo_real_10y else None

    # Precio del oro desde Yahoo (GC=F) ya en historico o en precios
    oro_precio = precios.get("oro") or precios.get("gld")

    # Lógica estratégica Tipo Real vs Oro
    alerta_drenaje = False
    señal_oro_real = "neutro"
    desc_oro_real  = "Tipos reales en rango normal"

    if tipo_real_v is not None:
        if tipo_real_v < 0:
            señal_oro_real = "favorable_qqqqqq"  # dinero fiat se devalúa → activos alternativos
            desc_oro_real  = f"Tipos reales negativos ({tipo_real_v}%) — entorno favorable para tecnológicas y activos de riesgo"
        elif tipo_real_v < 0.5:
            señal_oro_real = "neutro_bajo"
            desc_oro_real  = f"Tipos reales bajos ({tipo_real_v}%) — soporte moderado para QQQ"
        elif tipo_real_v < 1.5:
            señal_oro_real = "advertencia"
            desc_oro_real  = f"Tipos reales en ascenso ({tipo_real_v}%) — vigilar rotación a renta fija"
        elif tipo_real_v < 2.5:
            señal_oro_real = "drenaje_liquidez"
            alerta_drenaje = True
            desc_oro_real  = f"⚠️ Tipos reales elevados ({tipo_real_v}%) — DRENAJE DE LIQUIDEZ, coste oportunidad alto para QQQ"
        else:
            señal_oro_real = "drenaje_extremo"
            alerta_drenaje = True
            desc_oro_real  = f"🔴 Tipos reales muy altos ({tipo_real_v}%) — ASFIXIA A NASDAQ, capital rota a renta fija"

    log.info(f"  Tipo Real 10Y: {tipo_real_v} → {señal_oro_real}")

    # ── 4. CURVA DE TIPOS COMPLETA ────────────────────────────────────────────
    dgs3mo = fred_vals.get("DGS3MO")
    dgs2   = fred_vals.get("DGS2")
    dgs5   = fred_vals.get("DGS5")
    dgs10  = fred_vals.get("DGS10")
    dgs30  = fred_vals.get("DGS30")

    # También intentar con TNX/IRX del histórico Yahoo como fallback
    tnx_raw = precios.get("tnx")

    t3m  = dgs3mo["v"] if dgs3mo else None
    t2y  = dgs2["v"]   if dgs2   else None
    t5y  = dgs5["v"]   if dgs5   else None
    t10y = dgs10["v"]  if dgs10  else (round(tnx_raw / 10, 3) if tnx_raw else None)
    t30y = dgs30["v"]  if dgs30  else None

    # Spreads
    sp_t10y_t2y = fred_vals.get("T10Y2Y")
    sp_t10y_t3m = fred_vals.get("T10Y3M")

    sp10_2  = sp_t10y_t2y["v"] if sp_t10y_t2y else (round(t10y - t2y, 3) if t10y and t2y else None)
    sp10_3m = sp_t10y_t3m["v"] if sp_t10y_t3m else (round(t10y - t3m, 3) if t10y and t3m else None)

    invertida_2y  = sp10_2  < 0 if sp10_2  is not None else None
    invertida_3m  = sp10_3m < 0 if sp10_3m is not None else None

    if sp10_3m is not None:
        if sp10_3m < -0.5:
            señal_recesion = "alta"
        elif sp10_3m < 0:
            señal_recesion = "media"
        else:
            señal_recesion = "baja"
    else:
        señal_recesion = None

    log.info(f"  Curva: 3M={t3m} 2Y={t2y} 5Y={t5y} 10Y={t10y} 30Y={t30y} | Spread10-2={sp10_2} Spread10-3m={sp10_3m}")

    # ── 5. CONDICIONES FINANCIERAS ────────────────────────────────────────────
    hy_spread = fred_vals.get("BAMLH0A0HYM2")
    nfci      = fred_vals.get("NFCI")
    fedfunds  = fred_vals.get("FEDFUNDS")
    sofr      = fred_vals.get("SOFR")

    hy_spread_v = hy_spread["v"] if hy_spread else None
    nfci_v      = nfci["v"]      if nfci      else None
    fedfunds_v  = fedfunds["v"]  if fedfunds  else None
    sofr_v      = sofr["v"]      if sofr      else None

    sofr_spread = round(sofr_v - fedfunds_v, 3) if sofr_v and fedfunds_v else None

    log.info(f"  Condiciones: HY_Spread={hy_spread_v} NFCI={nfci_v} FedFunds={fedfunds_v}% SOFR={sofr_v}%")

    # ── FASE 7: WLCFLPCL ventanilla descuento Fed ────────────────────────────
    wlcflpcl = fred_vals.get("WLCFLPCL")

    # ── 6. DXY CORRELACIÓN MÓVIL CON QQQ ─────────────────────────────────────
    corr_dxy_30d  = None
    corr_dxy_90d  = None
    dxy_señal     = "neutro"
    dxy_desc      = "Correlación DXY-QQQ en rango normal"

    try:
        col_dxy = "DXY_close"
        col_qqq = "QQQ_close"
        if col_dxy in df_maestro.columns and col_qqq in df_maestro.columns:
            dxy_s = df_maestro[col_dxy].dropna()
            qqq_s = df_maestro[col_qqq].dropna()

            # Alinear por índice
            aligned = pd.concat([dxy_s, qqq_s], axis=1, join="inner").dropna()
            aligned.columns = ["dxy", "qqq"]

            # Retornos diarios
            ret = aligned.pct_change().dropna()

            if len(ret) >= 90:
                corr_dxy_30d = round(float(ret.tail(30)["dxy"].corr(ret.tail(30)["qqq"])), 3)
                corr_dxy_90d = round(float(ret.tail(90)["dxy"].corr(ret.tail(90)["qqq"])), 3)

                # DXY reciente: velocidad
                dxy_roc5 = round((aligned["dxy"].iloc[-1] / aligned["dxy"].iloc[-6] - 1) * 100, 2) if len(aligned) >= 6 else None

                if dxy_roc5 is not None:
                    if dxy_roc5 > 1.5:
                        dxy_señal = "dollar_squeeze"
                        dxy_desc  = f"⚠️ DXY +{dxy_roc5}% en 5 días — Dollar Squeeze: presión bajista en márgenes Big Tech"
                    elif dxy_roc5 < -1.5:
                        dxy_señal = "dolar_debil_alcista"
                        dxy_desc  = f"✅ DXY {dxy_roc5}% en 5 días — Dólar débil: entorno favorable para tech y emergentes"
                    else:
                        dxy_señal = "neutro"
                        dxy_desc  = f"DXY estable (ROC5={dxy_roc5}%) — correlación 30d={corr_dxy_30d}, 90d={corr_dxy_90d}"

                log.info(f"  DXY Corr 30d={corr_dxy_30d} 90d={corr_dxy_90d} | Señal={dxy_señal}")
    except Exception as e:
        log.warning(f"  [!] Correlación DXY-QQQ error: {e}")

    # ── 7. SCORE MACRO REAL ───────────────────────────────────────────────────
    def calcular_score_macro_real() -> float:
        s = 0.0

        # Balance Fed (WALCL): expansión es positivo
        if walcl_raw:
            if walcl_raw.get("trend") == "up":   s += 1.0
            elif walcl_raw.get("trend") == "down": s -= 0.5

        # Liquidez Neta: si crece, alcista
        if liquidez_neta_trend == "up":    s += 1.5
        elif liquidez_neta_trend == "down": s -= 1.0

        # Fed Funds: bajo = favorable
        if fedfunds_v is not None:
            if fedfunds_v < 3:    s += 1.5
            elif fedfunds_v < 4:  s += 0.5
            elif fedfunds_v > 5:  s -= 1.0
            elif fedfunds_v > 5.5: s -= 2.0

        # HY Spread: bajo = apetito riesgo
        if hy_spread_v is not None:
            if hy_spread_v < 2.5:   s += 1.5
            elif hy_spread_v < 3.5: s += 0.5
            elif hy_spread_v > 5.0: s -= 2.0
            elif hy_spread_v > 4.0: s -= 1.0

        # NFCI: negativo = condiciones financieras laxas (alcista)
        if nfci_v is not None:
            if nfci_v < -0.5:   s += 1.5
            elif nfci_v < 0:    s += 0.5
            elif nfci_v > 0.3:  s -= 1.0
            elif nfci_v > 0.7:  s -= 2.0

        # Spread 10Y-3M: el más fiable para recesión
        if sp10_3m is not None:
            if sp10_3m < -0.5:   s -= 2.0
            elif sp10_3m < 0:    s -= 1.0
            elif sp10_3m > 0.5:  s += 0.5

        # SOFR spread: discrepancia indica stress interbancario
        if sofr_spread is not None and abs(sofr_spread) > 0.5:
            s -= 1.5

        # Tipos reales: clave para QQQ
        if tipo_real_v is not None:
            if tipo_real_v < 0:    s += 1.5
            elif tipo_real_v < 1:  s += 0.5
            elif tipo_real_v > 2:  s -= 1.5
            elif tipo_real_v > 1.5: s -= 1.0

        # Inflación esperada (T5YIE)
        if t5yie and t5yie["v"] is not None:
            ie = t5yie["v"]
            if ie < 2.0:    s += 0.5
            elif ie > 3.0:  s -= 0.5
            elif ie > 3.5:  s -= 1.0

        # DXY señal
        if dxy_señal == "dolar_debil_alcista":   s += 1.0
        elif dxy_señal == "dollar_squeeze":       s -= 1.5

        # FASE 7: Ventanilla Descuento Fed (WLCFLPCL) — estres bancario
        if wlcflpcl and wlcflpcl.get("v") and wlcflpcl.get("prev") and wlcflpcl["prev"]:
            try:
                if float(wlcflpcl["v"]) > float(wlcflpcl["prev"]) * 1.5:
                    s -= 1.5
                    log.warning("  [FRED] WLCFLPCL sube >50% - estres bancario sistemico detectado")
            except Exception:
                pass

        # FASE 7: CPI YoY
        if cpi_yoy is not None:
            if cpi_yoy > 4.0:   s -= 1.0
            elif cpi_yoy < 2.0: s += 0.5

        return round(max(-8, min(8, s)), 1)

    score_macro = calcular_score_macro_real()
    log.info(f"  Score macro FRED: {score_macro:+.1f}")

    # ── 8. CONSTRUIR OBJETO macro COMPLETO ───────────────────────────────────
    return {
        "curva": {
            "t3m":  t3m,
            "t2y":  t2y,
            "t5y":  t5y,
            "t10y": t10y,
            "t30y": t30y,
            "sp10_2":  sp10_2,
            "sp10_3m": sp10_3m,
            "invertida2y":  invertida_2y,
            "invertida3m":  invertida_3m,
            "señalRecesion": señal_recesion,
        },
        "fred": {
            "walcl":    walcl_raw,
            "wtregen":  wtregen_raw,
            "rrpontsyd": rrponts_raw,
            "fedfunds": fedfunds,
            "sofr":     sofr,
            "hySpread": hy_spread,
            "nfci":     nfci,
            "t5yie":    t5yie,
            "t10yie":   t10yie,
            "t5y5y":    t5y5y,
            "tipoReal10y": tipo_real_10y,
            "sofrSpread":  sofr_spread,
            # Fase 7
            "wlcflpcl": wlcflpcl,
            "cpi_yoy":  cpi_yoy,
        },
        "liquidezNeta": {
            "valor":  liquidez_neta,
            "trend":  liquidez_neta_trend,
            "walcl":  walcl_raw["v"] if walcl_raw else None,
            "wtregen": wtregen_raw["v"] if wtregen_raw else None,
            "rrpontsyd": rrponts_raw["v"] if rrponts_raw else None,
            "desc":   f"Liquidez Neta = WALCL - TGA - RRP = {liquidez_neta:,.0f}M" if liquidez_neta else "No disponible",
        },
        "tiposRealesOro": {
            "tipoReal":  tipo_real_v,
            "señal":     señal_oro_real,
            "alerta":    alerta_drenaje,
            "desc":      desc_oro_real,
            "oroPrice":  oro_precio,
        },
        "dxy": {
            "corr30d":  corr_dxy_30d,
            "corr90d":  corr_dxy_90d,
            "señal":    dxy_señal,
            "desc":     dxy_desc,
        },
        "score": score_macro,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  ██████╗  MÓDULO FASE 3 — COT (CFTC)
# ─────────────────────────────────────────────────────────────────────────────



# =============================================================================
#                                                                            ##
#   ████  BLOQUE CSV LOCAL — CAPA AUTORITATIVA (prevalece sobre APIs) ████  ##
#                                                                            ##
#   Lee directamente de los CSV en DATA_CSV_DIR.                             ##
#   - leer_cot_csv()             → COT NASDAQ MINI con percentiles 1044sem   ##
#   - leer_vix_vvix_skew_csv()   → VIX+VVIX+SKEW + ratio + term structure    ##
#   - leer_dix_gex_csv()         → DIX% + GEX (B$) SqueezeMetrics            ##
#   - leer_qqq_opciones_csv()    → Max Pain + muros OI + PCR (Barchart)      ##
#                                                                            ##
#   Estas funciones provienen del antiguo actualizar_radar_csv.py.           ##
#   Si producen datos validos, SOBRESCRIBEN los calculados por las APIs.    ##
# =============================================================================

import csv as _csv_csv
import re as _csv_re
from datetime import datetime as _dt_csv, timedelta as _td_csv

def _csv_log(msg):
    """Wrapper para logger del bloque CSV."""
    log.info(f"  [CSV] {msg}")

def _csv_percentil(serie, valor):
    """Percentil de 'valor' dentro de 'serie' (lista de floats). 0-100."""
    if not serie or valor is None:
        return None
    return round(sum(1 for x in serie if x <= valor) / len(serie) * 100, 1)

def _csv_tendencia_n(serie_ordenada, n=4):
    """Devuelve 'subiendo', 'bajando' o 'estable' comparando ultimos n/2 vs anteriores n/2."""
    if len(serie_ordenada) < n:
        return "insuficiente"
    mitad = n // 2
    recientes  = serie_ordenada[-mitad:]
    anteriores = serie_ordenada[-n:-mitad]
    avg_rec = sum(recientes) / len(recientes)
    avg_ant = sum(anteriores) / len(anteriores)
    diff_pct = (avg_rec - avg_ant) / abs(avg_ant) * 100 if avg_ant != 0 else 0
    if diff_pct > 3:
        return "subiendo"
    if diff_pct < -3:
        return "bajando"
    return "estable"

def _csv_parse_fecha(s):
    """Parsea los distintos formatos de fecha de los TXT del CFTC y CSV CBOE."""
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt_csv.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

def _csv_safe_float(s):
    """Convierte string a float tolerando espacios, comas y puntos."""
    try:
        return float(str(s).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


# -----------------------------------------------------------------------------
# CSV-1) COT — CFTC Financial Futures TFF (NASDAQ MINI 209742)
# -----------------------------------------------------------------------------

def leer_cot_csv():
    """
    Lee todos los TXT del CFTC en COT_CSV_DIR, extrae el NASDAQ MINI (209742),
    calcula percentiles con el historico completo y devuelve un dict con
    valores actuales + serie historica para el dashboard.
    """
    if not COT_CSV_DIR.exists():
        _csv_log(f"COT: carpeta {COT_CSV_DIR} no existe - saltando capa CSV COT")
        return None

    txt_files = sorted(COT_CSV_DIR.glob("*.txt")) + sorted(COT_CSV_DIR.glob("*.TXT"))
    if not txt_files:
        _csv_log(f"COT: no se encontraron TXT en {COT_CSV_DIR}")
        return None

    _csv_log(f"COT: leyendo {len(txt_files)} TXT en {COT_CSV_DIR}...")

    all_rows = {}  # fecha -> dict (deduplicar)
    for path in txt_files:
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as f:
                reader = _csv_csv.DictReader(f)
                for row in reader:
                    code = row.get("CFTC_Contract_Market_Code", "").strip()
                    if code != "209742":
                        continue
                    fecha = _csv_parse_fecha(row.get("Report_Date_as_YYYY-MM-DD", ""))
                    if not fecha:
                        continue
                    all_rows[fecha] = row
        except Exception as e:
            _csv_log(f"COT: {path.name}: {e}")

    if not all_rows:
        _csv_log("COT: no se encontraron datos NASDAQ MINI (209742)")
        return None

    serie_raw = sorted(all_rows.items())

    serie = []
    for fecha, row in serie_raw:
        lev_l = _csv_safe_float(row.get("Lev_Money_Positions_Long_All"))
        lev_s = _csv_safe_float(row.get("Lev_Money_Positions_Short_All"))
        dl_l  = _csv_safe_float(row.get("Dealer_Positions_Long_All"))
        dl_s  = _csv_safe_float(row.get("Dealer_Positions_Short_All"))
        am_l  = _csv_safe_float(row.get("Asset_Mgr_Positions_Long_All"))
        am_s  = _csv_safe_float(row.get("Asset_Mgr_Positions_Short_All"))
        oi    = _csv_safe_float(row.get("Open_Interest_All"))
        if None in (lev_l, lev_s, dl_l, dl_s, am_l, am_s):
            continue
        lev_tot = lev_l + lev_s
        serie.append({
            "fecha":       str(fecha),
            "oi":          int(oi) if oi else 0,
            "lev_l":       int(lev_l),
            "lev_s":       int(lev_s),
            "lev_net":     int(lev_l - lev_s),
            "lev_pct_l":   round(lev_l / lev_tot * 100, 1) if lev_tot > 0 else 0,
            "dealer_l":    int(dl_l),
            "dealer_s":    int(dl_s),
            "dealer_net":  int(dl_l - dl_s),
            "assetmgr_l":  int(am_l),
            "assetmgr_s":  int(am_s),
            "assetmgr_net":int(am_l - am_s),
        })

    n_total = len(serie)
    if n_total == 0:
        return None
    _csv_log(f"COT: {n_total} semanas cargadas ({serie[0]['fecha']} -> {serie[-1]['fecha']})")

    pcts_l = sorted([r["lev_pct_l"] for r in serie])  # SORTED para percentiles correctos

    p10 = pcts_l[int(n_total * 0.10)] if n_total > 10 else pcts_l[0]
    p25 = pcts_l[int(n_total * 0.25)] if n_total > 4  else pcts_l[0]
    p75 = pcts_l[int(n_total * 0.75)] if n_total > 4  else pcts_l[-1]
    p90 = pcts_l[int(n_total * 0.90)] if n_total > 10 else pcts_l[-1]

    actual = serie[-1]
    pct_hist = _csv_percentil(pcts_l, actual["lev_pct_l"])

    ultimos_nets = [r["lev_net"]   for r in serie[-8:]]
    ultimos_pcts = [r["lev_pct_l"] for r in serie[-8:]]
    tend_pct = _csv_tendencia_n(ultimos_pcts, 4)

    prev = serie[-2] if len(serie) >= 2 else None
    cambio_net = actual["lev_net"] - prev["lev_net"] if prev else None
    cambio_pct = round(actual["lev_pct_l"] - prev["lev_pct_l"], 1) if prev else None

    pct_l = actual["lev_pct_l"]
    if pct_l <= p10:
        senal     = "alcista_extremo"
        senal_txt = f"Fondos muy cortos ({pct_l:.0f}% largos, p{pct_hist:.0f}) - senal contraria ALCISTA FUERTE"
        fuerza    = "extremo"
    elif pct_l <= p25:
        senal     = "alcista"
        senal_txt = f"Fondos cortos ({pct_l:.0f}% largos, p{pct_hist:.0f}) - sesgo alcista"
        fuerza    = "fuerte"
    elif pct_l >= p90:
        senal     = "bajista_extremo"
        senal_txt = f"Fondos muy largos ({pct_l:.0f}% largos, p{pct_hist:.0f}) - senal contraria BAJISTA FUERTE"
        fuerza    = "extremo"
    elif pct_l >= p75:
        senal     = "bajista"
        senal_txt = f"Fondos largos ({pct_l:.0f}% largos, p{pct_hist:.0f}) - sesgo bajista"
        fuerza    = "fuerte"
    else:
        senal     = "neutro"
        senal_txt = f"Posicionamiento neutro ({pct_l:.0f}% largos, p{pct_hist:.0f})"
        fuerza    = "neutro"

    _csv_log(f"COT -> {senal_txt}")

    hist_52 = [
        {
            "fecha":        r["fecha"],
            "lev_l":        r["lev_l"],
            "lev_s":        r["lev_s"],
            "lev_net":      r["lev_net"],
            "lev_pct_l":    r["lev_pct_l"],
            "dealer_net":   r["dealer_net"],
            "assetmgr_net": r["assetmgr_net"],
        }
        for r in serie[-52:]
    ]

    return {
        # Datos actuales
        "fecha":          actual["fecha"],
        "lev_largos":     actual["lev_l"],
        "lev_cortos":     actual["lev_s"],
        "lev_neto":       actual["lev_net"],
        "lev_pct_largos": actual["lev_pct_l"],
        "dealer_neto":    actual["dealer_net"],
        "assetmgr_neto":  actual["assetmgr_net"],
        "open_interest":  actual["oi"],
        # Contexto historico
        "percentil_historico":  pct_hist,
        "semanas_historico":    n_total,
        "tendencia_4s":         tend_pct,
        "cambio_semana_neto":   cambio_net,
        "cambio_semana_pct":    cambio_pct,
        # Senal
        "señal":          senal,
        "señal_texto":    senal_txt,
        "fuerza":         fuerza,
        # Umbrales calibrados
        "umbrales": {
            "alcista_extremo_p10": round(p10, 1),
            "alcista_fuerte_p25":  round(p25, 1),
            "bajista_fuerte_p75":  round(p75, 1),
            "bajista_extremo_p90": round(p90, 1),
        },
        # Serie historica 52 semanas
        "historico_52s": hist_52,
        "fuente": "CFTC TXT local (CSV)",
    }


# -----------------------------------------------------------------------------
# CSV-2) VIX + VVIX + SKEW (CBOE)
# -----------------------------------------------------------------------------

def _csv_senal_vix_compuesta(vix_s, ratio_s, skew_s, mom_s):
    """Combina las 4 senales VIX en una senal resumen."""
    puntos_alcista = 0
    puntos_bajista = 0
    if vix_s   == "panico":            puntos_alcista += 2
    if vix_s   == "complacencia":      puntos_bajista += 2
    if ratio_s == "miedo_extremo":     puntos_alcista += 2
    if ratio_s == "complacencia":      puntos_bajista += 1
    if skew_s  == "cola_extrema":      puntos_bajista += 2
    if skew_s  == "cola_elevada":      puntos_bajista += 1
    if mom_s   == "spike_bajista":     puntos_alcista += 1
    if puntos_alcista >= 3:
        return "alcista"
    if puntos_bajista >= 3:
        return "bajista"
    return "neutro"


def leer_vix_vvix_skew_csv():
    """
    Lee los 3 CSV de CBOE, calcula senales derivadas y devuelve dict con
    valores actuales, percentiles historicos y serie 90 dias.
    """
    if not VIX_CSV.exists():
        _csv_log(f"VIX: {VIX_CSV} no existe - saltando capa CSV VIX/VVIX/SKEW")
        return None

    _csv_log("VIX+VVIX+SKEW: leyendo CSV CBOE...")

    # --- VIX ---
    vix = {}
    try:
        with open(VIX_CSV, newline="", encoding="utf-8") as f:
            for row in _csv_csv.DictReader(f):
                d = _csv_parse_fecha(row.get("DATE", ""))
                c = _csv_safe_float(row.get("CLOSE"))
                if d and c:
                    vix[d] = c
        _csv_log(f"VIX: {len(vix)} dias ({min(vix)} -> {max(vix)})")
    except Exception as e:
        _csv_log(f"VIX error: {e}")
        return None

    # --- VVIX ---
    vvix = {}
    if VVIX_CSV.exists():
        try:
            with open(VVIX_CSV, newline="", encoding="utf-8") as f:
                for row in _csv_csv.DictReader(f):
                    d = _csv_parse_fecha(row.get("DATE", ""))
                    v = _csv_safe_float(row.get("VVIX"))
                    if d and v:
                        vvix[d] = v
            _csv_log(f"VVIX: {len(vvix)} dias")
        except Exception as e:
            _csv_log(f"VVIX warning: {e}")

    # --- SKEW ---
    skew = {}
    if SKEW_CSV.exists():
        try:
            with open(SKEW_CSV, newline="", encoding="utf-8") as f:
                for row in _csv_csv.DictReader(f):
                    d = _csv_parse_fecha(row.get("DATE", ""))
                    s = _csv_safe_float(row.get("SKEW"))
                    if d and s:
                        skew[d] = s
            _csv_log(f"SKEW: {len(skew)} dias")
        except Exception as e:
            _csv_log(f"SKEW warning: {e}")

    if not vix:
        return None

    ultima_vix  = max(vix.keys())
    ultima_vvix = max(vvix.keys()) if vvix else None
    ultima_skew = max(skew.keys()) if skew else None

    vix_spot = vix[ultima_vix]
    vvix_val = vvix.get(ultima_vvix) if ultima_vvix else None
    skew_val = skew.get(ultima_skew) if ultima_skew else None

    todos_vix  = sorted(vix.values())
    todos_vvix = sorted(vvix.values()) if vvix else []
    todos_skew = sorted(skew.values()) if skew else []

    pct_vix  = _csv_percentil(todos_vix,  vix_spot)
    pct_vvix = _csv_percentil(todos_vvix, vvix_val) if vvix_val else None
    pct_skew = _csv_percentil(todos_skew, skew_val) if skew_val else None

    ratio = round(vvix_val / vix_spot, 2) if vvix_val and vix_spot > 0 else None

    ratios_hist = []
    for d in vix:
        if d in vvix and vix[d] > 0:
            ratios_hist.append(vvix[d] / vix[d])
    ratios_hist.sort()
    pct_ratio = _csv_percentil(ratios_hist, ratio) if ratio else None

    if ratio:
        if ratio > 7.0:
            ratio_senal = "miedo_extremo"
            ratio_txt   = f"VVIX/VIX={ratio:.1f}x - demanda extrema de proteccion institucional"
        elif ratio > 6.0:
            ratio_senal = "miedo_elevado"
            ratio_txt   = f"VVIX/VIX={ratio:.1f}x - mercado nervioso, volatilidad cara"
        elif ratio < 3.5:
            ratio_senal = "complacencia"
            ratio_txt   = f"VVIX/VIX={ratio:.1f}x - complacencia, volatilidad barata"
        else:
            ratio_senal = "normal"
            ratio_txt   = f"VVIX/VIX={ratio:.1f}x - regimen normal"
    else:
        ratio_senal, ratio_txt = "sin_datos", "VVIX no disponible"

    # --- Term Structure proxy: VIX MA5 vs MA20 ---
    vix_sorted_dates = sorted(vix.keys())
    def vix_ma(fecha, n):
        vals = []
        d = fecha
        while len(vals) < n and d >= vix_sorted_dates[0]:
            if d in vix:
                vals.append(vix[d])
            d -= _td_csv(days=1)
        return sum(vals) / len(vals) if vals else None

    ma5  = vix_ma(ultima_vix, 5)
    ma20 = vix_ma(ultima_vix, 20)

    if ma5 and ma20 and ma20 > 0:
        ts_spread = (ma5 - ma20) / ma20 * 100
        if ts_spread > 8:
            ts_senal = "backwardation"
            ts_txt   = f"VIX MA5({ma5:.1f}) >> MA20({ma20:.1f}): estres agudo -> rebote probable 2-5d"
        elif ts_spread > 3:
            ts_senal = "tension"
            ts_txt   = f"VIX MA5({ma5:.1f}) > MA20({ma20:.1f}): tension creciente"
        elif ts_spread < -5:
            ts_senal = "contango_pronunciado"
            ts_txt   = f"VIX MA5({ma5:.1f}) << MA20({ma20:.1f}): calma pronunciada, complacencia posible"
        else:
            ts_senal = "contango_normal"
            ts_txt   = f"VIX MA5({ma5:.1f}) ~ MA20({ma20:.1f}): estructura normal"
    else:
        ts_senal, ts_txt, ts_spread = "sin_datos", "Datos insuficientes", None

    # --- Momentum VIX 5d ---
    d5 = ultima_vix - _td_csv(days=7)
    vix_5d = None
    for _ in range(7):
        if d5 in vix:
            vix_5d = vix[d5]
            break
        d5 -= _td_csv(days=1)
    mom_5d = round((vix_spot - vix_5d) / vix_5d * 100, 1) if vix_5d else None
    if   mom_5d and mom_5d > 20: mom_senal = "spike_bajista"
    elif mom_5d and mom_5d > 5:  mom_senal = "subiendo"
    elif mom_5d and mom_5d < -10:mom_senal = "cayendo"
    else:                         mom_senal = "estable"

    # --- Senal VIX global ---
    if pct_vix <= 15:
        vix_senal = "complacencia"
        vix_txt   = f"VIX={vix_spot:.2f} (p{pct_vix:.0f}) - complacencia extrema"
    elif pct_vix >= 85:
        vix_senal = "panico"
        vix_txt   = f"VIX={vix_spot:.2f} (p{pct_vix:.0f}) - panico, rebote probable"
    elif pct_vix >= 70:
        vix_senal = "estres"
        vix_txt   = f"VIX={vix_spot:.2f} (p{pct_vix:.0f}) - estres elevado, vigilar"
    else:
        vix_senal = "normal"
        vix_txt   = f"VIX={vix_spot:.2f} (p{pct_vix:.0f}) - zona normal"

    # --- SKEW ---
    if skew_val and pct_skew is not None:
        if   pct_skew >= 90:
            skew_senal = "cola_extrema"
            skew_txt   = f"SKEW={skew_val:.1f} (p{pct_skew:.0f}) - compra masiva de puts OTM - cola bajista"
        elif pct_skew >= 75:
            skew_senal = "cola_elevada"
            skew_txt   = f"SKEW={skew_val:.1f} (p{pct_skew:.0f}) - proteccion de cola elevada"
        elif pct_skew <= 10:
            skew_senal = "cola_baja"
            skew_txt   = f"SKEW={skew_val:.1f} (p{pct_skew:.0f}) - sin demanda de proteccion"
        else:
            skew_senal = "normal"
            skew_txt   = f"SKEW={skew_val:.1f} (p{pct_skew:.0f}) - normal"
    else:
        skew_senal = "sin_datos"
        skew_txt   = "SKEW no disponible"

    _csv_log(f"VIX -> {vix_txt}")
    _csv_log(f"VVIX/VIX -> {ratio_txt}")
    _csv_log(f"SKEW -> {skew_txt}")

    cutoff_90 = ultima_vix - _td_csv(days=130)
    hist_90 = []
    for d in sorted(vix.keys()):
        if d < cutoff_90:
            continue
        hist_90.append({
            "fecha":  str(d),
            "vix":    vix[d],
            "vvix":   vvix.get(d),
            "skew":   skew.get(d),
            "ratio":  round(vvix[d] / vix[d], 2) if d in vvix and vix[d] > 0 else None,
        })

    return {
        "fecha_vix":      str(ultima_vix),
        "vix_spot":       round(vix_spot, 2),
        "vvix":           round(vvix_val, 2) if vvix_val else None,
        "skew":           round(skew_val, 1) if skew_val else None,
        "ratio_vvix_vix": ratio,
        "vix_percentil":  pct_vix,
        "vvix_percentil": pct_vvix,
        "skew_percentil": pct_skew,
        "ratio_percentil":pct_ratio,
        "vix_ma5":        round(ma5, 2)  if ma5  else None,
        "vix_ma20":       round(ma20, 2) if ma20 else None,
        "vix_mom_5d_pct": mom_5d,
        "vix_mom_señal":  mom_senal,
        "ts_spread_pct":  round(ts_spread, 1) if ts_spread is not None else None,
        "ts_señal":       ts_senal,
        "ts_texto":       ts_txt,
        "vix_señal":      vix_senal,
        "vix_texto":      vix_txt,
        "ratio_señal":    ratio_senal,
        "ratio_texto":    ratio_txt,
        "skew_señal":     skew_senal,
        "skew_texto":     skew_txt,
        "señal_global":   _csv_senal_vix_compuesta(vix_senal, ratio_senal, skew_senal, mom_senal),
        "historico_90d":  hist_90,
        "fuente":         "CBOE CSV local",
    }


# -----------------------------------------------------------------------------
# CSV-3) DIX + GEX (SqueezeMetrics)
# -----------------------------------------------------------------------------

def leer_dix_gex_csv():
    """
    Lee DIX.csv de SqueezeMetrics (columnas: date, price, dix [0-1], gex [USD]).
    Devuelve DIX en %, GEX en B$, percentiles, MAs y senal.
    """
    if not DIX_CSV.exists():
        _csv_log(f"DIX: {DIX_CSV} no existe - saltando capa CSV DIX/GEX")
        return None

    _csv_log("DIX+GEX: leyendo CSV SqueezeMetrics...")

    serie = []
    try:
        with open(DIX_CSV, newline="", encoding="utf-8") as f:
            for row in _csv_csv.DictReader(f):
                d     = _csv_parse_fecha(row.get("date", ""))
                dix_r = _csv_safe_float(row.get("dix"))
                gex_r = _csv_safe_float(row.get("gex"))
                price = _csv_safe_float(row.get("price"))
                if not (d and dix_r is not None and gex_r is not None):
                    continue
                serie.append({
                    "fecha": str(d),
                    "dix":   round(dix_r * 100, 2),
                    "gex":   round(gex_r / 1_000_000_000, 3),
                    "price": price,
                })
    except Exception as e:
        _csv_log(f"DIX error: {e}")
        return None

    if not serie:
        return None

    _csv_log(f"DIX: {len(serie)} dias ({serie[0]['fecha']} -> {serie[-1]['fecha']})")

    todos_dix = sorted(r["dix"] for r in serie)
    todos_gex = sorted(r["gex"] for r in serie)

    actual  = serie[-1]
    pct_dix = _csv_percentil(todos_dix, actual["dix"])
    pct_gex = _csv_percentil(todos_gex, actual["gex"])

    dix_20 = [r["dix"] for r in serie[-20:]]
    gex_20 = [r["gex"] for r in serie[-20:]]
    tend_dix = _csv_tendencia_n(dix_20, 6)
    tend_gex = _csv_tendencia_n(gex_20, 6)

    dix_ma5  = round(sum(r["dix"] for r in serie[-5:])  / min(5,  len(serie)), 2)
    dix_ma20 = round(sum(r["dix"] for r in serie[-20:]) / min(20, len(serie)), 2)
    gex_ma5  = round(sum(r["gex"] for r in serie[-5:])  / min(5,  len(serie)), 3)

    d = actual["dix"]
    if   d >= 47: dix_senal, dix_txt = "acumulacion_fuerte", f"DIX={d:.1f}% (p{pct_dix:.0f}) - acumulacion institucional fuerte en dark pools"
    elif d >= 44: dix_senal, dix_txt = "acumulacion",        f"DIX={d:.1f}% (p{pct_dix:.0f}) - acumulacion moderada"
    elif d <  38: dix_senal, dix_txt = "distribucion",       f"DIX={d:.1f}% (p{pct_dix:.0f}) - distribucion institucional"
    elif d <  41: dix_senal, dix_txt = "distribucion_leve", f"DIX={d:.1f}% (p{pct_dix:.0f}) - ligera presion vendedora"
    else:         dix_senal, dix_txt = "neutro",            f"DIX={d:.1f}% (p{pct_dix:.0f}) - actividad neutral"

    g = actual["gex"]
    if   g >= 8: gex_senal, gex_regimen, gex_txt = "anclaje_fuerte", "positivo_alto", f"GEX={g:.2f}B (p{pct_gex:.0f}) - dealers anclan precio con fuerza, baja volatilidad"
    elif g >= 2: gex_senal, gex_regimen, gex_txt = "anclaje",        "positivo",      f"GEX={g:.2f}B (p{pct_gex:.0f}) - gamma positiva, mercado estable"
    elif g >= 0: gex_senal, gex_regimen, gex_txt = "neutral",        "positivo_bajo", f"GEX={g:.2f}B (p{pct_gex:.0f}) - gamma baja, movimientos posibles"
    else:        gex_senal, gex_regimen, gex_txt = "amplificacion",  "negativo",      f"GEX={g:.2f}B (p{pct_gex:.0f}) - gamma NEGATIVA, dealers amplificaran movimientos"

    _csv_log(f"DIX -> {dix_txt}")
    _csv_log(f"GEX -> {gex_txt}")

    hist_90 = [{"fecha": r["fecha"], "dix": r["dix"], "gex": r["gex"]} for r in serie[-90:]]

    return {
        "fecha":            actual["fecha"],
        "dix":              actual["dix"],
        "gex_b":            actual["gex"],
        "precio_sp500":     actual["price"],
        "dix_percentil":    pct_dix,
        "gex_percentil":    pct_gex,
        "dix_ma5":          dix_ma5,
        "dix_ma20":         dix_ma20,
        "gex_ma5":          gex_ma5,
        "tendencia_dix_6d": tend_dix,
        "tendencia_gex_6d": tend_gex,
        "dix_señal":        dix_senal,
        "dix_texto":        dix_txt,
        "gex_señal":        gex_senal,
        "gex_regimen":      gex_regimen,
        "gex_texto":        gex_txt,
        "historico_90d":    hist_90,
        "fuente":           "SqueezeMetrics CSV local",
    }


# -----------------------------------------------------------------------------
# CSV-4) Opciones QQQ - Barchart (qqq_quotedata.csv)
# -----------------------------------------------------------------------------

def leer_qqq_opciones_csv():
    """
    Lee qqq_quotedata.csv de Barchart.
    Calcula Max Pain, top resistencias (calls), top soportes (puts) y PCR.
    """
    if not QQQ_OPC_CSV.exists():
        _csv_log(f"QQQ opciones: {QQQ_OPC_CSV} no existe - saltando capa CSV opciones")
        return None

    _csv_log("QQQ opciones: leyendo CSV Barchart...")

    try:
        rows_raw = []
        with open(QQQ_OPC_CSV, newline="", encoding="utf-8") as f:
            for r in _csv_csv.reader(f):
                rows_raw.append(r)
    except Exception as e:
        _csv_log(f"QQQ opciones error: {e}")
        return None

    if len(rows_raw) < 4:
        return None

    # Precio QQQ desde cabecera Barchart
    precio_qqq = None
    for row in rows_raw[:3]:
        for cell in row:
            m = _csv_re.search(r"Last:\s*([\d.]+)", str(cell))
            if m:
                precio_qqq = float(m.group(1))
                break
        if precio_qqq:
            break
    if not precio_qqq:
        precio_qqq = 0.0
    _csv_log(f"QQQ precio (CSV): {precio_qqq}")

    # Agrupar OI por vencimiento
    exp_data = {}
    for row in rows_raw[3:]:
        if len(row) < 22:
            continue
        try:
            expiry = row[0].strip()
            strike = _csv_safe_float(row[11])
            c_oi   = _csv_safe_float(row[10]) or 0
            p_oi   = _csv_safe_float(row[21]) or 0
            if not expiry or not strike or strike <= 0:
                continue
            if expiry not in exp_data:
                exp_data[expiry] = {}
            exp_data[expiry][strike] = {"c_oi": int(c_oi), "p_oi": int(p_oi)}
        except Exception:
            continue

    if not exp_data:
        _csv_log("QQQ opciones: no se pudo parsear el CSV")
        return None

    # Vencimiento con mas OI (mas liquido)
    exp_oi_total = {exp: sum(d["c_oi"] + d["p_oi"] for d in strikes.values())
                    for exp, strikes in exp_data.items()}
    exp_target = max(exp_oi_total, key=exp_oi_total.get)
    strikes_data = exp_data[exp_target]
    _csv_log(f"Vencimiento seleccionado: {exp_target} (OI total: {exp_oi_total[exp_target]:,})")

    # Filtrado +-25% del precio
    if precio_qqq > 0:
        rango_min = precio_qqq * 0.75
        rango_max = precio_qqq * 1.25
        strikes_filtrados = {s: d for s, d in strikes_data.items() if rango_min <= s <= rango_max}
    else:
        strikes_filtrados = strikes_data

    def calcular_max_pain(sd):
        strikes = sorted(sd.keys())
        dolor = {}
        for test in strikes:
            total = 0
            for s, d in sd.items():
                if test < s:
                    total += d["c_oi"] * (s - test)
                elif test > s:
                    total += d["p_oi"] * (test - s)
            dolor[test] = total
        return min(dolor, key=dolor.get) if dolor else None

    max_pain = calcular_max_pain(strikes_filtrados)

    calls_arriba = [(s, d["c_oi"]) for s, d in strikes_filtrados.items()
                    if s > precio_qqq and d["c_oi"] > 0]
    calls_arriba.sort(key=lambda x: -x[1])
    top_calls = [{"strike": s, "oi": oi} for s, oi in calls_arriba[:3]]

    puts_abajo = [(s, d["p_oi"]) for s, d in strikes_filtrados.items()
                  if s < precio_qqq and d["p_oi"] > 0]
    puts_abajo.sort(key=lambda x: -x[1])
    top_puts = [{"strike": s, "oi": oi} for s, oi in puts_abajo[:3]]

    total_c = sum(d["c_oi"] for d in strikes_filtrados.values())
    total_p = sum(d["p_oi"] for d in strikes_filtrados.values())
    pcr     = round(total_p / total_c, 2) if total_c > 0 else None

    if max_pain and precio_qqq > 0:
        dist_mp = round((max_pain - precio_qqq) / precio_qqq * 100, 1)
        if dist_mp < -5:
            mp_senal = "bajista"
            mp_txt   = f"Max Pain={max_pain} ({dist_mp:+.1f}%) - precio por encima, presion bajista al vencimiento"
        elif dist_mp > 5:
            mp_senal = "alcista"
            mp_txt   = f"Max Pain={max_pain} ({dist_mp:+.1f}%) - precio por debajo, presion alcista al vencimiento"
        else:
            mp_senal = "neutro"
            mp_txt   = f"Max Pain={max_pain} ({dist_mp:+.1f}%) - precio cerca del Max Pain, rango estable"
    else:
        dist_mp, mp_senal, mp_txt = None, "sin_datos", "Max Pain no calculable"

    if pcr:
        if   pcr > 1.5: pcr_senal, pcr_txt = "miedo",      f"PCR={pcr:.2f} - ratio puts/calls alto, mercado comprando proteccion"
        elif pcr > 1.0: pcr_senal, pcr_txt = "precaucion", f"PCR={pcr:.2f} - sesgo hacia puts, cautela institucional"
        elif pcr < 0.6: pcr_senal, pcr_txt = "euforia",    f"PCR={pcr:.2f} - exceso de calls, posible senal de euforia"
        else:           pcr_senal, pcr_txt = "normal",     f"PCR={pcr:.2f} - equilibrio normal calls/puts"
    else:
        pcr_senal, pcr_txt = "sin_datos", "PCR no calculable"

    resist_1  = top_calls[0]["strike"] if top_calls else None
    soporte_1 = top_puts[0]["strike"]  if top_puts  else None

    _csv_log(f"Max Pain -> {mp_txt}")
    _csv_log(f"Resistencia: {resist_1} | Soporte: {soporte_1}")
    _csv_log(f"PCR -> {pcr_txt}")

    return {
        "vencimiento":      exp_target,
        "precio_qqq":       precio_qqq,
        "max_pain":         max_pain,
        "dist_max_pain_pct":dist_mp,
        "max_pain_señal":   mp_senal,
        "max_pain_texto":   mp_txt,
        "resistencia_1":    resist_1,
        "soporte_1":        soporte_1,
        "top_resistencias": top_calls,
        "top_soportes":     top_puts,
        "pcr":              pcr,
        "pcr_señal":        pcr_senal,
        "pcr_texto":        pcr_txt,
        "total_calls_oi":   total_c,
        "total_puts_oi":    total_p,
        "fuente":           "Barchart QQQ CSV local",
    }


# -----------------------------------------------------------------------------
# CSV-5) MAPEADORES - adaptan el output CSV al esquema legacy del JSON
# -----------------------------------------------------------------------------

def mapear_cot_csv_al_legacy(cot_csv: dict, cot_legacy: dict = None) -> dict:
    """
    Convierte el output de leer_cot_csv() al esquema 'cot' esperado por el
    frontend (largos, cortos, neto, pctLargo, cambioNeto, trend4w, senal,
    senalDealers, netoDealers...). Conserva campos legacy no solapados.
    """
    if not cot_csv:
        return cot_legacy or {}
    base = dict(cot_legacy) if cot_legacy else {}
    # NOTA: el COT del CSV usa Lev_Money (hedge funds). El legacy usaba NonComm.
    # Lev_Money es el subgrupo MAS importante de NonComm -> es upgrade, no perdida.

    # trend4w (legacy/score_cot_fn/index.html) es NUMERICO: cambio en contratos
    # netos a 4 semanas (curr - hace 4 semanas), NO la etiqueta "subiendo/bajando"
    # de tendencia_4s (esa es un string y va en su propio campo, ver mas abajo).
    hist52 = cot_csv.get("historico_52s") or []
    trend4w_num = (hist52[-1]["lev_net"] - hist52[-5]["lev_net"]) if len(hist52) >= 5 else None

    base.update({
        "fecha":         cot_csv.get("fecha"),
        "largos":        cot_csv.get("lev_largos"),
        "cortos":        cot_csv.get("lev_cortos"),
        "neto":          cot_csv.get("lev_neto"),
        "pctLargo":      cot_csv.get("lev_pct_largos"),
        "cambioNeto":    cot_csv.get("cambio_semana_neto"),
        "trend4w":       trend4w_num,
        "tendencia_4s":  cot_csv.get("tendencia_4s"),  # string subiendo/bajando/estable -> icono frontend
        "señal":         cot_csv.get("señal"),
        "desc":          cot_csv.get("señal_texto"),
        "señalDealers":  "neutro",  # CSV no clasifica dealers como "acumulacion/distribucion"
        "netoDealers":   cot_csv.get("dealer_neto"),
        "fuente":        cot_csv.get("fuente"),
        # extras enriquecidos del CSV
        "percentil_historico": cot_csv.get("percentil_historico"),
        "semanas_historico":   cot_csv.get("semanas_historico"),
        "umbrales":            cot_csv.get("umbrales"),
        "historico_52s":       cot_csv.get("historico_52s"),
        "assetmgr_neto":       cot_csv.get("assetmgr_neto"),
        "open_interest":       cot_csv.get("open_interest"),
        "fuerza":              cot_csv.get("fuerza"),
        # eliminar el campo "error" legacy si existia (CSV es exito)
        "error":               None,
    })
    return base


def mapear_qqq_csv_al_legacy(qqq_csv: dict, opc_legacy: dict = None) -> dict:
    """
    Convierte el output de leer_qqq_opciones_csv() al esquema 'opciones' legacy
    (v1, v2, v3, gex, pcrOI, pcrVol...). El CSV solo tiene 1 vencimiento, asi que
    v2/v3 se conservan del legacy si existian.
    """
    if not qqq_csv:
        return opc_legacy or {}
    base = dict(opc_legacy) if opc_legacy else {}

    precio_ref = qqq_csv.get("precio_qqq") or 1
    # v1 desde CSV (vencimiento mas liquido de Barchart)
    v1_csv = {
        "fecha":    qqq_csv.get("vencimiento"),
        "maxPain":  qqq_csv.get("max_pain"),
        "distPct":  qqq_csv.get("dist_max_pain_pct"),
        "topCalls": [{"strike": float(c["strike"]),
                      "oi": int(c["oi"]),
                      "dist": round((float(c["strike"]) - precio_ref) / precio_ref * 100, 2)}
                     for c in (qqq_csv.get("top_resistencias") or [])],
        "topPuts":  [{"strike": float(p["strike"]),
                      "oi": int(p["oi"]),
                      "dist": round((float(p["strike"]) - precio_ref) / precio_ref * 100, 2)}
                     for p in (qqq_csv.get("top_soportes") or [])],
        "señal":    qqq_csv.get("max_pain_señal"),
        "desc":     qqq_csv.get("max_pain_texto"),
    }

    base["v1"]     = v1_csv
    base["precio"] = qqq_csv.get("precio_qqq")
    base["pcrOI"]  = qqq_csv.get("pcr")
    base["error"]  = None
    base["fuente"] = qqq_csv.get("fuente")

    # extras enriquecidos
    base["resistencia_1"]  = qqq_csv.get("resistencia_1")
    base["soporte_1"]      = qqq_csv.get("soporte_1")
    base["total_calls_oi"] = qqq_csv.get("total_calls_oi")
    base["total_puts_oi"]  = qqq_csv.get("total_puts_oi")
    return base


def mapear_pcr_csv_al_legacy(qqq_csv: dict, pcr_legacy: dict = None) -> dict:
    """
    PCR derivado del CSV de opciones QQQ. El campo 'equity' usaba PCR.txt CBOE
    (todas las equity options del mercado). El CSV solo tiene PCR de QQQ -> es
    un proxy razonable pero NO identico. Conservamos PCR.txt legacy si existe.
    """
    if not qqq_csv:
        return pcr_legacy or {}
    base = dict(pcr_legacy) if pcr_legacy else {}
    pcr_qqq = qqq_csv.get("pcr")

    # Si el legacy ya tenia equity/total de PCR.txt CBOE, no lo pisamos: es mas
    # representativo del mercado completo que el PCR del CSV de QQQ aislado.
    if not base.get("equity") and not base.get("total"):
        base["equity"] = pcr_qqq
        base["total"]  = pcr_qqq
        base["señal"]  = qqq_csv.get("pcr_señal")
        base["desc"]   = qqq_csv.get("pcr_texto")
        base["fuente"] = "qqq_quotedata_csv"
        base["error"]  = None

    # Siempre anadir el PCR especifico de QQQ como dato extra
    base["pcr_qqq"]        = pcr_qqq
    base["pcr_qqq_señal"]  = qqq_csv.get("pcr_señal")
    base["pcr_qqq_texto"]  = qqq_csv.get("pcr_texto")
    return base


def mapear_vix_csv_al_legacy(vix_csv: dict, vix_ts_legacy: dict = None) -> dict:
    """
    El CSV de VIX/VVIX/SKEW aporta info que el vixTS legacy NO tenia:
    spot diario, percentiles historicos, ratio VVIX/VIX, SKEW, momentum.
    El legacy vixTS sigue siendo necesario porque tiene la term structure de
    futuros (vx1/vx2) y backwardation. Hacemos MERGE conservando ambos.
    """
    if not vix_csv:
        return vix_ts_legacy or {}
    base = dict(vix_ts_legacy) if vix_ts_legacy else {}

    # El spot del CSV puede ser mas reciente que el del historico -> usar CSV
    if vix_csv.get("vix_spot"):
        base["spot"] = vix_csv["vix_spot"]
    # Percentil historico solo en CSV
    if vix_csv.get("vix_percentil") is not None:
        base["vixPercentil"] = vix_csv["vix_percentil"]
    # Si CSV no tiene futuros pero legacy si, conservar futuros legacy
    # (vx1, vx2, backwardation, spread1, etc. se mantienen tal cual)

    # Anadir bloque enriquecido como subcampo
    base["csv_extras"] = {
        "vvix":           vix_csv.get("vvix"),
        "skew":           vix_csv.get("skew"),
        "ratio_vvix_vix": vix_csv.get("ratio_vvix_vix"),
        "vvix_percentil": vix_csv.get("vvix_percentil"),
        "skew_percentil": vix_csv.get("skew_percentil"),
        "ratio_percentil":vix_csv.get("ratio_percentil"),
        "vix_ma5":        vix_csv.get("vix_ma5"),
        "vix_ma20":       vix_csv.get("vix_ma20"),
        "vix_mom_5d_pct": vix_csv.get("vix_mom_5d_pct"),
        "ts_proxy_señal": vix_csv.get("ts_señal"),
        "ts_proxy_texto": vix_csv.get("ts_texto"),
        "señal_compuesta_csv": vix_csv.get("señal_global"),
    }
    return base


# =============================================================================
#  FIN BLOQUE CSV LOCAL - vuelve a la logica original del actualizar_radar.py
# =============================================================================



# ─────────────────────────────────────────────────────────────────────────────
#  MÓDULO: parsear_cot_txt — Lee COT.txt descargado del CFTC
#  Ruta esperada: BASE_DIR / "COT.txt"
#  Formato: TFF (Traders in Financial Futures) — Legacy Futures Only
#  Descarga: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
#           → "Financial Futures" → "Traders in Financial Futures"
#  Contrato objetivo: NASDAQ MINI (CFTC Code #209742)
#  Columnas de posiciones (en orden en la línea "Positions"):
#    Dealer L/S/Spr | AssetMgr L/S/Spr | Leveraged L/S/Spr | Other L/S/Spr | NonRep L/S
#  El frontend Táctico 2-5D busca: largos, cortos, neto, leveraged_long/short,
#  pctLargo, cambioNeto, señal, fecha, fecha_reporte
# ─────────────────────────────────────────────────────────────────────────────

def parsear_cot_txt(base_dir: Path = None) -> dict:
    """
    Lee COT.txt del CFTC (sección Financial Futures / TFF) y extrae
    el bloque NASDAQ MINI (código 209742).

    Posiciones en orden de columna (14 valores por fila):
      [0]  Dealer Long       [1]  Dealer Short      [2]  Dealer Spread
      [3]  Asset Mgr Long    [4]  Asset Mgr Short   [5]  Asset Mgr Spread
      [6]  Leveraged Long    [7]  Leveraged Short   [8]  Leveraged Spread
      [9]  Other Long        [10] Other Short       [11] Other Spread
      [12] NonRep Long       [13] NonRep Short

    El frontend usa Leveraged Funds como proxy de Large Speculators NQ.

    Devuelve None si no encuentra el archivo o el bloque NASDAQ MINI.
    """
    if base_dir is None:
        base_dir = BASE_DIR

    candidatos = [base_dir / "COT.txt", base_dir / "cot.txt", base_dir / "COT.TXT"]
    ruta = next((p for p in candidatos if p.exists()), None)
    if ruta is None:
        return None

    try:
        texto = ruta.read_text(encoding="latin-1", errors="replace")
        lineas = texto.splitlines()

        import re as _re

        # ── Extraer fecha del reporte del header ──────────────────────────────
        fecha_reporte = None
        fecha_iso     = None
        for linea in lineas[:5]:
            m = _re.search(r"as of\s+(\w+ \d+,\s*\d+)", linea, _re.IGNORECASE)
            if m:
                fecha_raw = m.group(1).strip()
                try:
                    from datetime import datetime as _dt
                    dt = _dt.strptime(fecha_raw, "%B %d, %Y")
                    fecha_reporte = fecha_raw
                    fecha_iso     = dt.strftime("%Y-%m-%d")
                except ValueError:
                    fecha_reporte = fecha_raw
                break

        # ── Localizar el bloque NASDAQ MINI (código 209742) ───────────────────
        # La línea objetivo tiene simultáneamente "209742" y "Open Interest"
        # p.ej: "CFTC Code #209742   Open Interest is   314,972"
        # La siguiente línea es "Positions" y la siguiente a esa son los datos.
        bloque_inicio = None
        for i, linea in enumerate(lineas):
            if "209742" in linea and "Open Interest" in linea:
                bloque_inicio = i
                break

        if bloque_inicio is None:
            log.warning("  [COT-TXT] Código 209742 (NASDAQ MINI) no encontrado en COT.txt")
            return None

        # ── Parsear las 4 secciones del bloque ────────────────────────────────
        # Buscamos dentro de las siguientes 20 líneas desde bloque_inicio
        bloque = lineas[bloque_inicio: bloque_inicio + 25]

        def _extraer_numeros(linea):
            """Extrae todos los enteros de una línea (ignora puntos decimales)."""
            tokens = _re.findall(r"[-]?\d[\d,]*", linea)
            result = []
            for t in tokens:
                try:
                    result.append(int(t.replace(",", "")))
                except ValueError:
                    pass
            return result

        posiciones   = None
        cambios      = None
        open_interest = None

        estado = "buscando"
        for linea in bloque:
            linea_strip = linea.strip()

            # Open Interest
            m_oi = _re.search(r"Open Interest is\s+([\d,]+)", linea_strip)
            if m_oi:
                try:
                    open_interest = int(m_oi.group(1).replace(",", ""))
                except ValueError:
                    pass

            if linea_strip.startswith("Positions"):
                estado = "posiciones_siguiente"
                continue
            if estado == "posiciones_siguiente" and linea_strip:
                nums = _extraer_numeros(linea_strip)
                if len(nums) >= 14:
                    posiciones = nums[:14]
                estado = "buscando"
                continue

            if linea_strip.startswith("Changes from:"):
                estado = "cambios_siguiente"
                continue
            if estado == "cambios_siguiente" and linea_strip:
                nums = _extraer_numeros(linea_strip)
                if len(nums) >= 14:
                    cambios = nums[:14]
                estado = "buscando"
                continue

        if posiciones is None:
            log.warning("  [COT-TXT] No se pudo parsear la línea Positions del NASDAQ MINI")
            return None

        # ── Extraer campos por posición ───────────────────────────────────────
        dealer_l       = posiciones[0];  dealer_s       = posiciones[1]
        asset_l        = posiciones[3];  asset_s        = posiciones[4]
        leveraged_l    = posiciones[6];  leveraged_s    = posiciones[7]
        other_l        = posiciones[9];  other_s        = posiciones[10]

        # Cambios (si disponibles)
        cambio_lev_l = cambios[6] if cambios and len(cambios) > 6 else None
        cambio_lev_s = cambios[7] if cambios and len(cambios) > 7 else None
        cambio_dealer_l = cambios[0] if cambios else None

        neto_lev  = leveraged_l - leveraged_s
        total_lev = leveraged_l + leveraged_s
        pct_largo = round(leveraged_l / total_lev * 100, 1) if total_lev > 0 else None

        cambio_neto = (cambio_lev_l - cambio_lev_s) if (cambio_lev_l is not None and cambio_lev_s is not None) else None

        # Señal interpretativa (idéntica a calcular_cot)
        if pct_largo is not None:
            if   pct_largo > 75: señal = "bajista";     desc = f"Specs {pct_largo}% largos — sobreposicionamiento, contrarian bajista"
            elif pct_largo > 65: señal = "bajista_mod"; desc = f"Specs {pct_largo}% largos — posicionamiento elevado, precaución"
            elif pct_largo < 25: señal = "alcista";     desc = f"Specs {pct_largo}% largos — capitulación, señal contraria alcista"
            elif pct_largo < 35: señal = "alcista_mod"; desc = f"Specs {pct_largo}% largos — posicionamiento bajo, sesgo alcista"
            else:                señal = "neutro";      desc = f"Specs {pct_largo}% largos — posicionamiento neutral"
        else:
            señal = "neutro"; desc = "Datos insuficientes"

        log.info(
            f"  [COT-TXT] OK — fecha={fecha_iso or fecha_reporte} | "
            f"Lev_Long={leveraged_l:,} Lev_Short={leveraged_s:,} "
            f"Neto={neto_lev:+,} ({pct_largo}%) | {señal.upper()}"
        )

        return {
            # Campos compatibles con calcular_cot (mismo formato)
            "fecha":         fecha_iso or fecha_reporte or "desconocida",
            "fecha_reporte": fecha_reporte,
            # Leveraged Funds = Large Speculators proxy para NQ
            "largos":          leveraged_l,
            "cortos":          leveraged_s,
            "neto":            neto_lev,
            "leveraged_long":  leveraged_l,
            "leveraged_short": leveraged_s,
            # Asset Manager (dealers/institucionales)
            "dealers_largo":   dealer_l,
            "dealers_corto":   dealer_s,
            "netoDealers":     dealer_l - dealer_s,
            "asset_largo":     asset_l,
            "asset_corto":     asset_s,
            # Estadísticos
            "pctLargo":        pct_largo,
            "pctDealers":      round(dealer_l / (dealer_l + dealer_s) * 100, 1) if (dealer_l + dealer_s) > 0 else None,
            "open_interest":   open_interest,
            "cambioNeto":      cambio_neto,
            "cambioNetoDealers": (cambio_dealer_l - cambios[1]) if (cambio_dealer_l is not None and cambios and len(cambios) > 1) else None,
            "trend4w":         None,   # solo hay 1 semana en el TXT; requeriría histórico
            "señal":           señal,
            "señalDealers":    "neutro",  # calculamos más abajo si hay cambios
            "desc":            desc,
            "historial":       [],
            "fuente":          "cftc_txt_manual",
            "fuente_verificacion": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        }

    except Exception as e:
        log.warning(f"  [COT-TXT] Error parseando COT.txt: {e}")
        import traceback
        log.warning(traceback.format_exc())
        return None


def calcular_cot() -> dict:
    """
    COT oficial CFTC — tres fuentes con fallback automático:
      1. ZIP directo CFTC  (misma fuente que cot-reports, sin dependencia externa)
      2. cot-reports       (si está instalado y funciona)
      3. CFTC OData API    (endpoint corregido)
    Datos 100% oficiales en las tres fuentes.
    Fuente verificable: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
    """
    import io, zipfile, requests

    log.info("  [COT] Iniciando módulo CFTC...")

    # ── FUENTE 0: COT.txt manual (mayor prioridad) ────────────────────────────
    cot_txt = parsear_cot_txt(BASE_DIR)
    if cot_txt is not None:
        log.info(f"  [COT] ✅ Fuente 0 (COT.txt manual): largos={cot_txt['largos']:,} cortos={cot_txt['cortos']:,} | {cot_txt['señal'].upper()}")
        return cot_txt

    # ── FUENTE 1: ZIP directo del CFTC (más fiable) ───────────────────────────
    def _via_zip_directo():
        anio = datetime.now().year
        urls = [
            f"https://www.cftc.gov/files/dea/history/fut_disagg_txtonly_{anio}.zip",
            f"https://www.cftc.gov/files/dea/history/com_disagg_txtonly_{anio}.zip",
            # Fallback año anterior (útil en enero)
            f"https://www.cftc.gov/files/dea/history/fut_disagg_txtonly_{anio-1}.zip",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    nombre = z.namelist()[0]
                    with z.open(nombre) as f:
                        df = pd.read_csv(f, encoding="latin-1", low_memory=False)

                mask = df["Market_and_Exchange_Names"].str.contains("NASDAQ MINI", case=False, na=False)
                df_nq = df[mask].copy()
                if df_nq.empty:
                    continue

                df_nq = df_nq.sort_values("Report_Date_as_YYYY_MM_DD", ascending=False).head(4).reset_index(drop=True)
                rows = [_parse_cot_row(df_nq.iloc[i]) for i in range(len(df_nq))]
                log.info(f"  [COT] ZIP CFTC OK ({url.split('/')[-1]}): {len(rows)} semanas")
                return rows, "cftc_zip_directo"
            except Exception as e:
                log.warning(f"  [COT] ZIP {url.split('/')[-1]} falló: {e}")
        return None, None

    # ── FUENTE 2: cot-reports (si está disponible) ────────────────────────────
    def _via_cot_reports():
        try:
            import cot_reports as cot
            df = cot.cot_year(year=datetime.now().year, cot_report_type="legacy_futonly")
            if df is None or df.empty:
                raise ValueError("vacío")
            mask = df["Market_and_Exchange_Names"].str.contains("NASDAQ MINI", case=False, na=False)
            df_nq = df[mask].sort_values("Report_Date_as_YYYY_MM_DD", ascending=False).head(4).reset_index(drop=True)
            if df_nq.empty:
                raise ValueError("sin filas NASDAQ MINI")
            rows = [_parse_cot_row(df_nq.iloc[i]) for i in range(len(df_nq))]
            log.info(f"  [COT] cot-reports OK: {len(rows)} semanas")
            return rows, "cot_reports"
        except Exception as e:
            log.warning(f"  [COT] cot-reports falló: {e}")
            return None, None

    # ── FUENTE 3: CFTC Socrata API (endpoint vigente 2026) ───────────────────
    def _via_cftc_api():
        try:
            # API Socrata — endpoint confirmado operativo mayo 2026
            # Dataset: Legacy Futures Only (6dca-aqww)
            # Nombre exacto verificado: "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE"
            from urllib.parse import urlencode
            params = urlencode({
                "$where": "market_and_exchange_names like '%NASDAQ MINI%'",
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": "4",
            })
            url = f"https://publicreporting.cftc.gov/resource/6dca-aqww.json?{params}"
            r = requests.get(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}, timeout=25)
            r.raise_for_status()
            data = r.json()
            if not data or not isinstance(data, list):
                raise ValueError("lista vacía o formato inesperado")
            rows = [_parse_cot_row_api(row) for row in data]
            log.info(f"  [COT] CFTC Socrata API OK: {len(rows)} semanas, última: {rows[0]['fecha']}")
            return rows, "cftc_socrata_api"
        except Exception as e:
            log.warning(f"  [COT] CFTC Socrata API falló: {e}")
            return None, None

    # ── PARSER UNIFICADO ──────────────────────────────────────────────────────
    def _parse_cot_row(row):
        """Parsea fila de CSV (cot-reports o ZIP directo)."""
        def gi(keys):
            for k in keys:
                for col in row.index:
                    if k.lower() in col.lower():
                        try: return int(float(str(row[col]).replace(",", "")))
                        except: pass
            return 0
        largos_nc  = gi(["Noncommercial_Positions_Long_All", "NonComm_Positions_Long_All"])
        cortos_nc  = gi(["Noncommercial_Positions_Short_All", "NonComm_Positions_Short_All"])
        largos_com = gi(["Commercial_Positions_Long_All", "Comm_Positions_Long_All"])
        cortos_com = gi(["Commercial_Positions_Short_All", "Comm_Positions_Short_All"])
        return {
            "fecha": str(row.get("Report_Date_as_YYYY_MM_DD", ""))[:10],
            "largos": largos_nc, "cortos": cortos_nc,
            "neto": largos_nc - cortos_nc,
            "dealers_largo": largos_com, "dealers_corto": cortos_com,
            "netoDealers": largos_com - cortos_com,
        }

    def _parse_cot_row_api(row):
        """Parsea fila de la CFTC Socrata API JSON.
        Campos en minúsculas con guión bajo — confirmados en respuesta real mayo 2026.
        """
        def gi(*keys):
            for k in keys:
                v = row.get(k) or row.get(k.lower()) or 0
                try: return int(float(str(v).replace(",", "")))
                except: pass
            return 0
        # Nombres Socrata confirmados: noncomm_positions_long_all, comm_positions_long_all
        largos_nc  = gi("noncomm_positions_long_all",  "NonComm_Positions_Long_All")
        cortos_nc  = gi("noncomm_positions_short_all", "NonComm_Positions_Short_All")
        largos_com = gi("comm_positions_long_all",  "Comm_Positions_Long_All")
        cortos_com = gi("comm_positions_short_all", "Comm_Positions_Short_All")
        # Fecha: campo Socrata devuelve "2026-05-19T00:00:00.000"
        fecha_raw = row.get("report_date_as_yyyy_mm_dd") or row.get("Report_Date_as_YYYY_MM_DD", "")
        return {
            "fecha": str(fecha_raw)[:10],
            "largos": largos_nc, "cortos": cortos_nc,
            "neto": largos_nc - cortos_nc,
            "dealers_largo": largos_com, "dealers_corto": cortos_com,
            "netoDealers": largos_com - cortos_com,
        }

    # ── EJECUTAR con cascada de fallbacks ─────────────────────────────────────
    rows, fuente = _via_zip_directo()
    if not rows:
        rows, fuente = _via_cot_reports()
    if not rows:
        rows, fuente = _via_cftc_api()
    if not rows:
        log.error("  [COT] Todas las fuentes fallaron")
        return {
            "error": "todas_fuentes_fallaron",
            "fuente_verificacion": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
            "señal": "neutro", "desc": "COT no disponible — verificar manualmente",
            "largos": None, "cortos": None, "neto": None,
            "pctLargo": None, "cambioNeto": None, "trend4w": None,
            "señalDealers": "neutro", "netoDealers": None,
        }

    curr     = rows[0]
    prev_row = rows[1] if len(rows) > 1 else None
    row_4w   = rows[3] if len(rows) >= 4 else None

    total_nc    = curr["largos"] + curr["cortos"]
    pct_largo   = round(curr["largos"] / total_nc * 100, 1) if total_nc > 0 else None
    total_com   = curr["dealers_largo"] + curr["dealers_corto"]
    pct_dealers = round(curr["dealers_largo"] / total_com * 100, 1) if total_com > 0 else None

    cambio_neto         = curr["neto"] - prev_row["neto"] if prev_row else None
    cambio_neto_dealers = curr["netoDealers"] - prev_row["netoDealers"] if prev_row else None
    trend_4w            = curr["neto"] - row_4w["neto"] if row_4w else None

    if pct_largo is not None:
        if pct_largo > 75:   señal = "bajista";     desc = f"Specs {pct_largo}% largos — sobreposicionamiento, contrarian bajista"
        elif pct_largo > 65: señal = "bajista_mod"; desc = f"Specs {pct_largo}% largos — posicionamiento elevado, precaución"
        elif pct_largo < 25: señal = "alcista";     desc = f"Specs {pct_largo}% largos — capitulación, señal contraria alcista"
        elif pct_largo < 35: señal = "alcista_mod"; desc = f"Specs {pct_largo}% largos — posicionamiento bajo, sesgo alcista"
        else:                señal = "neutro";      desc = f"Specs {pct_largo}% largos — posicionamiento neutral"
    else:
        señal = "neutro"; desc = "Datos insuficientes"

    señal_dealers = "neutro"
    if cambio_neto_dealers is not None and cambio_neto is not None:
        if cambio_neto_dealers > 0 and cambio_neto < 0:   señal_dealers = "acumulacion"
        elif cambio_neto_dealers < 0 and cambio_neto > 0: señal_dealers = "distribucion"

    historial = [{"fecha": r["fecha"], "neto": r["neto"], "largos": r["largos"], "cortos": r["cortos"]} for r in rows]

    log.info(f"  [COT] {curr['fecha']} | Neto={curr['neto']:+,} | %Largos={pct_largo}% | {señal.upper()} | fuente={fuente}")

    return {
        "fecha": curr["fecha"], "largos": curr["largos"], "cortos": curr["cortos"],
        "neto": curr["neto"], "netoDealers": curr["netoDealers"],
        "pctLargo": pct_largo, "pctDealers": pct_dealers,
        "cambioNeto": cambio_neto, "cambioNetoDealers": cambio_neto_dealers,
        "trend4w": trend_4w, "señal": señal, "desc": desc,
        "señalDealers": señal_dealers, "historial": historial,
        "fuente": fuente,
        "fuente_verificacion": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  ██████╗  MÓDULO FASE 3 — OPTIONS CHAIN QQQ (Max Pain + GEX + PCR)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_opciones_qqq(precios: dict) -> dict:
    """
    Módulo Fase 3: Cadena de opciones del QQQ vía yfinance.

    Calcula para los 3 primeros vencimientos:
      - Max Pain (nivel de mínimo dolor para compradores de opciones)
      - Top 5 strikes por OI en calls y puts
      - GEX estimado sintético basado en VIX
      - PCR (Put/Call Ratio) por OI y por volumen

    Devuelve dict compatible con nq-multihor.html.
    """
    log.info("  [OPC] Iniciando módulo Options Chain QQQ...")
    try:
        import yfinance as yf

        qqq = yf.Ticker("QQQ")
        precio_qqq = precios.get("qqq")

        # Obtener vencimientos disponibles
        try:
            opciones_info = qqq.options  # tuple de fechas
        except Exception as e:
            raise ValueError(f"yfinance options no disponible: {e}")

        if not opciones_info or len(opciones_info) == 0:
            raise ValueError("No hay vencimientos disponibles para QQQ")

        if precio_qqq is None:
            try:
                precio_qqq = float(qqq.fast_info["lastPrice"])
            except Exception:
                precio_qqq = precios.get("qqq") or 450.0

        log.info(f"  [OPC] QQQ precio={precio_qqq:.2f} | {len(opciones_info)} vencimientos disponibles")

        # Analizar los 3 primeros vencimientos
        vencimientos_a_analizar = list(opciones_info)[:3]
        resultados_venc = []
        pcr_calls_oi_total = 0
        pcr_puts_oi_total  = 0
        pcr_calls_vol_total = 0
        pcr_puts_vol_total  = 0

        for exp_fecha in vencimientos_a_analizar:
            try:
                chain = qqq.option_chain(exp_fecha)
                calls = chain.calls
                puts  = chain.puts

                if calls.empty and puts.empty:
                    log.warning(f"  [OPC] Venc {exp_fecha}: cadena vacía, saltando")
                    continue

                # Acumular totales para PCR global
                pcr_calls_oi_total  += int(calls["openInterest"].fillna(0).sum())
                pcr_puts_oi_total   += int(puts["openInterest"].fillna(0).sum())
                pcr_calls_vol_total += int(calls["volume"].fillna(0).sum())
                pcr_puts_vol_total  += int(puts["volume"].fillna(0).sum())

                # ── MAX PAIN ─────────────────────────────────────────────────
                # Filtrar solo strikes con OI real y dentro de ±20% del precio
                # (Yahoo no devuelve OI para vencimientos muy próximos → evita MaxPain absurdo)
                calls_oi = calls[
                    (calls["openInterest"].fillna(0) > 0) &
                    (calls["strike"] >= precio_qqq * 0.80) &
                    (calls["strike"] <= precio_qqq * 1.20)
                ].copy()
                puts_oi = puts[
                    (puts["openInterest"].fillna(0) > 0) &
                    (puts["strike"] >= precio_qqq * 0.80) &
                    (puts["strike"] <= precio_qqq * 1.20)
                ].copy()

                oi_total_venc = int(calls_oi["openInterest"].sum()) + int(puts_oi["openInterest"].sum())
                if oi_total_venc < 100:
                    log.warning(f"  [OPC] Venc {exp_fecha}: OI insuficiente ({oi_total_venc}), MaxPain no fiable — usando precio actual")
                    max_pain_strike = precio_qqq
                    dist_pct = 0.0
                    señal_mp = "neutro"
                    desc_mp  = f"Max Pain no calculable (OI insuficiente en venc. corto)"
                    resultados_venc.append({
                        "fecha":    exp_fecha,
                        "maxPain":  round(float(max_pain_strike), 2),
                        "distPct":  dist_pct,
                        "topCalls": [],
                        "topPuts":  [],
                        "señal":    señal_mp,
                        "desc":     desc_mp,
                    })
                    log.info(f"  [OPC] Venc {exp_fecha}: MaxPain=N/A (OI=0) | señal=neutro")
                    continue

                todos_strikes = sorted(set(
                    list(calls_oi["strike"].values) + list(puts_oi["strike"].values)
                ))
                min_dolor = float("inf")
                max_pain_strike = precio_qqq

                for s in todos_strikes:
                    dolor = 0.0
                    # Dolor a holders de calls: calls ITM (strike < s)
                    for _, row in calls_oi.iterrows():
                        if row["strike"] < s:
                            dolor += (s - row["strike"]) * (row["openInterest"] or 0)
                    # Dolor a holders de puts: puts ITM (strike > s)
                    for _, row in puts_oi.iterrows():
                        if row["strike"] > s:
                            dolor += (row["strike"] - s) * (row["openInterest"] or 0)
                    if dolor < min_dolor:
                        min_dolor = dolor
                        max_pain_strike = s

                dist_pct = round((max_pain_strike - precio_qqq) / precio_qqq * 100, 2) if precio_qqq else None

                # ── TOP 5 STRIKES por OI (±12% del precio) ───────────────────
                def top_strikes(df_opt, n=5):
                    rango = df_opt[
                        (df_opt["strike"] >= precio_qqq * 0.88) &
                        (df_opt["strike"] <= precio_qqq * 1.12) &
                        (df_opt["openInterest"].fillna(0) > 0)
                    ].copy()
                    rango = rango.sort_values("openInterest", ascending=False).head(n)
                    return [
                        {
                            "strike": float(r["strike"]),
                            "oi":     int(r["openInterest"] or 0),
                            "vol":    int(r["volume"] or 0),
                            "dist":   round((float(r["strike"]) - precio_qqq) / precio_qqq * 100, 2),
                        }
                        for _, r in rango.iterrows()
                    ]

                top_calls = top_strikes(calls)
                top_puts  = top_strikes(puts)

                # Señal según Max Pain
                if dist_pct is not None:
                    if dist_pct > 4:
                        señal_mp = "alcista"
                        desc_mp  = f"Max Pain {max_pain_strike:.0f} (+{dist_pct}%) — gravedad atrae precio arriba"
                    elif dist_pct < -4:
                        señal_mp = "bajista"
                        desc_mp  = f"Max Pain {max_pain_strike:.0f} ({dist_pct}%) — gravedad atrae precio abajo"
                    else:
                        señal_mp = "neutro"
                        desc_mp  = f"Max Pain {max_pain_strike:.0f} — precio cerca, zona equilibrio"
                else:
                    señal_mp = "neutro"
                    desc_mp  = "Max Pain no calculable"

                resultados_venc.append({
                    "fecha":    exp_fecha,
                    "maxPain":  round(float(max_pain_strike), 2),
                    "distPct":  dist_pct,
                    "topCalls": top_calls,
                    "topPuts":  top_puts,
                    "señal":    señal_mp,
                    "desc":     desc_mp,
                })
                log.info(f"  [OPC] Venc {exp_fecha}: MaxPain={max_pain_strike:.0f} ({dist_pct:+.2f}%) | señal={señal_mp}")

            except Exception as e:
                log.warning(f"  [OPC] Error procesando venc {exp_fecha}: {e}")
                continue

        if not resultados_venc:
            raise ValueError("No se pudo calcular ningún vencimiento")

        # ── PCR GLOBAL (por OI) ───────────────────────────────────────────────
        # Yahoo a veces no devuelve openInterest para vencimientos muy cortos.
        # Umbral mínimo de 500 contratos para considerar el OI fiable.
        # Si OI insuficiente, usamos volumen como proxy y lo marcamos.
        pcr_oi = round(pcr_puts_oi_total / pcr_calls_oi_total, 3) if pcr_calls_oi_total > 500 else None
        pcr_vol = round(pcr_puts_vol_total / pcr_calls_vol_total, 3) if pcr_calls_vol_total > 0 else None
        if pcr_oi is None and pcr_vol is not None:
            log.warning(f"  [OPC] PCR_OI no disponible (calls_OI={pcr_calls_oi_total}) — usando PCR_Vol como proxy")
            pcr_oi = pcr_vol

        # ── GEX SINTÉTICO basado en VIX ───────────────────────────────────────
        vix = precios.get("vix") or 20.0
        if vix < 16:
            gex_estado = "positivo_alto"
            gex_valor  = 3
            gex_desc   = "Gamma positiva alta — dealers estabilizan, mercado en rango"
        elif vix < 20:
            gex_estado = "positivo"
            gex_valor  = 2
            gex_desc   = "Gamma positiva — dealers comprando caídas"
        elif vix < 25:
            gex_estado = "neutro"
            gex_valor  = 0
            gex_desc   = "Gamma neutra — transición, mayor incertidumbre"
        elif vix < 30:
            gex_estado = "negativo"
            gex_valor  = -2
            gex_desc   = "Gamma negativa — dealers amplifican movimientos"
        else:
            gex_estado = "negativo_extremo"
            gex_valor  = -3
            gex_desc   = "Gamma negativa extrema — volatilidad amplificada, mercado inestable"

        # Detector de trampa alcista: precio sube pero VIX también sube
        trampa = False
        if vix > 20 and precios.get("qqq") is not None:
            trampa = vix > 22  # Simplificación; en Fase 3 no tenemos el precio anterior del VIX fácilmente
        if trampa:
            gex_desc = "⚠️ TRAMPA: VIX elevado — posible distribución institucional"

        log.info(f"  [OPC] GEX={gex_estado} ({gex_valor}) | PCR_OI={pcr_oi} | PCR_Vol={pcr_vol}")

        # ── FASE 7 A6: GEX REAL POR STRIKE ───────────────────────────────────
        gex_real_total  = None
        gamma_flip_level = None
        fuente_gex       = "sintetico"
        try:
            if resultados_venc:
                # Intentar calcular con el primer vencimiento (calls/puts cacheados arriba)
                # Recalcular accediendo al chain del primer venc para griegas
                exp_v1 = resultados_venc[0]["fecha"]
                chain_v1 = qqq.option_chain(exp_v1)
                calls_v1 = chain_v1.calls
                puts_v1  = chain_v1.puts
                if "gamma" in calls_v1.columns and "gamma" in puts_v1.columns:
                    precio_sq = precio_qqq ** 2 * 0.01
                    gex_por_strike = {}
                    for _, row in calls_v1.iterrows():
                        s = row["strike"]
                        gv = (row["gamma"] or 0) * (row["openInterest"] or 0) * 100 * precio_sq
                        gex_por_strike[s] = gex_por_strike.get(s, 0) + gv
                    for _, row in puts_v1.iterrows():
                        s = row["strike"]
                        gv = (row["gamma"] or 0) * (row["openInterest"] or 0) * 100 * precio_sq
                        gex_por_strike[s] = gex_por_strike.get(s, 0) - gv
                    gex_real_total = round(sum(gex_por_strike.values()), 0)
                    strikes_ord = sorted(gex_por_strike.keys())
                    gex_acum = 0
                    for s in strikes_ord:
                        gex_acum += gex_por_strike[s]
                        if gex_acum <= 0 and gamma_flip_level is None:
                            gamma_flip_level = s
                    fuente_gex = "real"
        except Exception:
            fuente_gex = "sintetico"

        dist_gamma_flip_pct = None
        if gamma_flip_level is not None and precio_qqq:
            dist_gamma_flip_pct = round((gamma_flip_level - precio_qqq) / precio_qqq * 100, 2)

        # ── LECTURA DE GEX MANUAL (gex_manual.json) ───────────────────────
        # Si existe gex_manual.json (generado por gex_parser.py), prevalece
        # sobre el calculado por yfinance. Tambien se extraen Max Pain y top OI
        # para auto-rellenar los inputs del Radar 2-5D mas adelante.
        gex_manual_payload = None
        gex_manual_path = BASE_DIR / "gex_manual.json"
        try:
            if gex_manual_path.exists():
                with open(gex_manual_path, "r", encoding="utf-8") as _f:
                    _gm = json.load(_f)
                _gen = _gm.get("generado", "")
                if _gen:
                    _dt = datetime.fromisoformat(_gen.replace("Z", ""))
                    _age_h = (datetime.now() - _dt).total_seconds() / 3600
                else:
                    _age_h = 0
                if _age_h < 24:
                    gex_manual_payload = _gm
                    gex_real_total      = _gm.get("valor_total")
                    gamma_flip_level    = _gm.get("gamma_flip_level")
                    dist_gamma_flip_pct = _gm.get("dist_gamma_flip_pct")
                    fuente_gex          = "gex_parser_local"
                    log.info(f"  [GEX] Cargado de gex_manual.json | total={gex_real_total} | flip={gamma_flip_level} | edad={_age_h:.1f}h")
                else:
                    log.info(f"  [GEX] gex_manual.json es antiguo ({_age_h:.1f}h>24h) — usando yfinance")
        except Exception as _e:
            log.warning(f"  [GEX] Error leyendo gex_manual.json: {_e}")

        gex_real_dict = {
            "valor_total":        gex_real_total,
            "gamma_flip_level":   gamma_flip_level,
            "dist_gamma_flip_pct": dist_gamma_flip_pct,
            "fuente":             fuente_gex,
        }

        # ── FASE 7 A7: SKEW DE OPCIONES ───────────────────────────────────────
        def calcular_skew_opciones(calls_s, puts_s, precio_s):
            try:
                strike_put_otm  = precio_s * 0.95
                strike_call_otm = precio_s * 1.05
                put_otm  = puts_s[abs(puts_s["strike"]  - strike_put_otm)  < precio_s * 0.02]
                call_otm = calls_s[abs(calls_s["strike"] - strike_call_otm) < precio_s * 0.02]
                if put_otm.empty or call_otm.empty:
                    return None
                if "impliedVolatility" not in put_otm.columns:
                    return None
                iv_put  = float(put_otm.sort_values("openInterest", ascending=False).iloc[0]["impliedVolatility"])
                iv_call = float(call_otm.sort_values("openInterest", ascending=False).iloc[0]["impliedVolatility"])
                if iv_call == 0:
                    return None
                skew_val = round(iv_put / iv_call, 3)
                if skew_val > 1.5:
                    senal_sk = "cisne_negro"
                    desc_sk  = "SKEW=" + str(skew_val) + " - cobertura institucional extrema contra colapso"
                elif skew_val > 1.3:
                    senal_sk = "elevado"
                    desc_sk  = "SKEW=" + str(skew_val) + " - cobertura activa, mercado nervioso"
                elif skew_val < 0.9:
                    senal_sk = "complacencia"
                    desc_sk  = "SKEW=" + str(skew_val) + " - sin cobertura, complacencia extrema"
                else:
                    senal_sk = "normal"
                    desc_sk  = "SKEW=" + str(skew_val) + " - cobertura normal"
                return {"valor": skew_val, "put_iv": round(iv_put, 4), "call_iv": round(iv_call, 4),
                        "senal": senal_sk, "desc": desc_sk}
            except Exception:
                return None

        skew_dict = None
        try:
            if resultados_venc:
                exp_v1  = resultados_venc[0]["fecha"]
                chain_v1 = qqq.option_chain(exp_v1)
                skew_dict = calcular_skew_opciones(chain_v1.calls, chain_v1.puts, precio_qqq)
        except Exception:
            skew_dict = None

        # ── FASE 7 A8: 0DTE RATIO ────────────────────────────────────────────
        from datetime import date as date_cls_dte
        hoy_str  = date_cls_dte.today().strftime("%Y-%m-%d")
        vol_0dte  = 0
        vol_total = 0
        try:
            for exp in list(opciones_info)[:10]:
                try:
                    chain_dte = qqq.option_chain(exp)
                    vol_exp = (int(chain_dte.calls["volume"].fillna(0).sum()) +
                               int(chain_dte.puts["volume"].fillna(0).sum()))
                    vol_total += vol_exp
                    if exp == hoy_str:
                        vol_0dte = vol_exp
                except Exception:
                    continue
        except Exception:
            pass

        ratio_0dte = round(vol_0dte / vol_total, 3) if vol_total > 0 else None
        if ratio_0dte is not None:
            if ratio_0dte > 0.45:
                senal_0dte = "extremo"
                desc_0dte  = "0DTE=" + str(round(ratio_0dte * 100, 1)) + "% - delta hedging forzado al cierre, amplificacion movimientos"
            elif ratio_0dte > 0.30:
                senal_0dte = "elevado"
                desc_0dte  = "0DTE=" + str(round(ratio_0dte * 100, 1)) + "% - actividad intradiaria elevada"
            else:
                senal_0dte = "normal"
                desc_0dte  = "0DTE=" + str(round(ratio_0dte * 100, 1)) + "% - actividad normal"
        else:
            senal_0dte = "sin_datos"
            desc_0dte  = "Sin vencimientos hoy"

        dte_dict = {
            "valor":     ratio_0dte,
            "vol_0dte":  vol_0dte,
            "vol_total": vol_total,
            "senal":     senal_0dte,
            "desc":      desc_0dte,
        }

        v1 = resultados_venc[0] if len(resultados_venc) > 0 else None
        v2 = resultados_venc[1] if len(resultados_venc) > 1 else None
        v3 = resultados_venc[2] if len(resultados_venc) > 2 else None

        return {
            "precio":       round(precio_qqq, 2),
            "vencimientos": resultados_venc,
            "v1":           v1,
            "v2":           v2,
            "v3":           v3,
            "gex": {
                "estado": gex_estado,
                "valor":  gex_valor,
                "trampa": trampa,
                "desc":   gex_desc,
            },
            "gex_real":   gex_real_dict,
            "skew":       skew_dict,
            "ratio_0dte": dte_dict,
            "pcrOI":  pcr_oi,
            "pcrVol": pcr_vol,
            "fuente": "yahoo_options",
            "_gex_manual_payload": gex_manual_payload,  # se usa para inyeccion posterior
        }

    except Exception as e:
        log.error(f"  [OPC] Error módulo opciones (yfinance): {e}")
        # ── FALLBACK: reconstruir desde gex_manual.json si existe ────────────
        # Esto ocurre en fin de semana o cuando yfinance tiene un bug de datetime.
        # gex_manual.json es generado por gex_parser.py con datos reales de Cboe.
        gex_manual_path = BASE_DIR / "gex_manual.json"
        if gex_manual_path.exists():
            try:
                with open(gex_manual_path, "r", encoding="utf-8") as _f:
                    _gm = json.load(_f)
                _gen = _gm.get("generado", "")
                _age_h = 0
                if _gen:
                    _dt = datetime.fromisoformat(_gen.replace("Z", ""))
                    _age_h = (datetime.now() - _dt).total_seconds() / 3600

                # Usar gex_manual si tiene menos de 72h (cubre fin de semana)
                if _age_h < 72:
                    log.info(f"  [OPC] Fallback a gex_manual.json OK (edad={_age_h:.1f}h)")
                    # Construir v1 desde el vencimiento próximo calculado por gex_parser
                    prox = _gm.get("vencimiento_proximo") or {}
                    maxpain_prox = prox.get("max_pain")
                    precio_ref   = _gm.get("precio_referencia") or precios.get("qqq") or 0
                    dist_mp      = round((maxpain_prox - precio_ref) / precio_ref * 100, 2) if (maxpain_prox and precio_ref) else None
                    v1_fb = {
                        "fecha":    prox.get("expiry", ""),
                        "maxPain":  maxpain_prox,
                        "distPct":  dist_mp,
                        "topCalls": prox.get("top_calls", []),
                        "topPuts":  prox.get("top_puts",  []),
                        "señal":    "neutro",
                        "desc":     f"Fallback gex_manual.json — MaxPain={maxpain_prox} ({dist_mp:+.2f}%)" if dist_mp else "Fallback gex_manual.json",
                    } if prox else None

                    # GEX desde gex_manual
                    gex_total = _gm.get("valor_total", 0)
                    gex_M     = _gm.get("valor_total_M", 0)
                    if   gex_M >  2: gex_estado = "positivo";  gex_desc = f"GEX={gex_M:.1f}M — dealers comprando caídas (soporte)"
                    elif gex_M < -2: gex_estado = "negativo";  gex_desc = f"GEX={gex_M:.1f}M — dealers amplificando movimientos (peligro)"
                    else:            gex_estado = "neutro";    gex_desc = f"GEX={gex_M:.1f}M — zona de transición"

                    gex_real_dict = {
                        "valor_total":         gex_total,
                        "gamma_flip_level":    _gm.get("gamma_flip_level"),
                        "dist_gamma_flip_pct": _gm.get("dist_gamma_flip_pct"),
                        "fuente":              "gex_parser_local (fallback yfinance)",
                    }

                    return {
                        "error":      None,
                        "precio":     precio_ref,
                        "vencimientos": [v1_fb] if v1_fb else [],
                        "v1":         v1_fb,
                        "v2":         None,
                        "v3":         None,
                        "gex": {
                            "estado": gex_estado,
                            "valor":  round(gex_M, 2),
                            "trampa": False,
                            "desc":   gex_desc,
                        },
                        "gex_real":   gex_real_dict,
                        "skew":       None,
                        "ratio_0dte": {"valor": None, "senal": "sin_datos", "desc": "No disponible (yfinance falló)"},
                        "pcrOI":      None,
                        "pcrVol":     None,
                        "fuente":     "gex_parser_local",
                        "_gex_manual_payload": _gm,
                    }
                else:
                    log.warning(f"  [OPC] gex_manual.json demasiado antiguo ({_age_h:.1f}h > 72h) — devolviendo error")
            except Exception as e2:
                log.warning(f"  [OPC] Fallback gex_manual.json también falló: {e2}")

        return {
            "error": str(e),
            "gex": {"estado": "neutro", "valor": 0, "trampa": False, "desc": "Opciones no disponibles"},
            "v1": None, "v2": None, "v3": None,
            "pcrOI": None, "pcrVol": None,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  MÓDULO: parsear_pcr_txt — Lee PCR.txt descargado manualmente de CBOE
#  Ruta esperada: BASE_DIR / "PCR.txt"
#  Formato: líneas de texto con "TOTAL PUT/CALL RATIO\t0.97" etc.
#  Prioridad: FUENTE 0 — prevalece sobre CBOE CSV y Yahoo Options
# ─────────────────────────────────────────────────────────────────────────────

def parsear_pcr_txt(base_dir: Path = None) -> dict:
    """
    Lee PCR.txt guardado manualmente en la carpeta del proyecto (nq-proxy).
    El archivo se descarga de https://www.cboe.com/data/market-statistics-historical-data/
    seleccionando la fecha más reciente en la sección Daily Market Statistics.

    Extrae:
      - TOTAL PUT/CALL RATIO      → pcr_total
      - EQUITY PUT/CALL RATIO     → pcr_equity
      - INDEX PUT/CALL RATIO      → pcr_index
      - SPX + SPXW PUT/CALL RATIO → pcr_spx
      - Fecha del reporte (ej: "05 June 2026")

    Devuelve None si el archivo no existe o no se puede parsear.
    """
    if base_dir is None:
        base_dir = BASE_DIR

    # Buscar el archivo: PCR.txt (insensible a mayúsculas en Windows vía Path)
    candidatos = [base_dir / "PCR.txt", base_dir / "pcr.txt", base_dir / "PCR.TXT"]
    ruta = next((p for p in candidatos if p.exists()), None)
    if ruta is None:
        return None

    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        lineas = texto.splitlines()

        pcr_total  = None
        pcr_equity = None
        pcr_index  = None
        pcr_spx    = None
        fecha_str  = None

        # Buscar la fecha del reporte (formato: "05 June 2026")
        import re
        for linea in lineas:
            m = re.match(r"^(\d{1,2}\s+\w+\s+\d{4})$", linea.strip())
            if m:
                fecha_str = m.group(1).strip()
                break

        # Parsear los ratios de la tabla tabulada
        for linea in lineas:
            linea = linea.strip()
            def _extract(etiqueta):
                if linea.startswith(etiqueta):
                    # Formato: "TOTAL PUT/CALL RATIO\t0.97"
                    # o:       "TOTAL PUT/CALL RATIO  0.97"
                    resto = linea[len(etiqueta):].strip().lstrip("\t").strip()
                    # Tomar solo el primer token numérico
                    tok = resto.split()[0] if resto else ""
                    tok = tok.replace(",", ".").strip()
                    try:
                        v = float(tok)
                        return round(v, 3) if v > 0 else None
                    except (ValueError, IndexError):
                        return None
                return None

            r = _extract("TOTAL PUT/CALL RATIO");  pcr_total  = r if r and pcr_total  is None else pcr_total
            r = _extract("EQUITY PUT/CALL RATIO");  pcr_equity = r if r and pcr_equity is None else pcr_equity
            r = _extract("INDEX PUT/CALL RATIO");   pcr_index  = r if r and pcr_index  is None else pcr_index
            r = _extract("SPX + SPXW PUT/CALL RATIO"); pcr_spx = r if r and pcr_spx   is None else pcr_spx

        if pcr_total is None and pcr_equity is None:
            log.warning("  [PCR-TXT] Archivo encontrado pero no se pudo extraer ningún ratio")
            return None

        # Verificar frescura: si la fecha del archivo es de hace más de 5 días,
        # avisar pero usar igualmente (puede ser el último dato disponible)
        edad_dias = None
        if fecha_str:
            try:
                from datetime import datetime as _dt_cls
                fecha_rep = _dt_cls.strptime(fecha_str, "%d %B %Y")
                edad_dias = (datetime.now() - fecha_rep).days
                if edad_dias > 5:
                    log.warning(f"  [PCR-TXT] Dato de hace {edad_dias} días ({fecha_str}) — puede no ser el último")
                else:
                    log.info(f"  [PCR-TXT] Fecha reporte: {fecha_str} ({edad_dias}d)")
            except Exception:
                pass

        # Señal interpretativa (igual que calcular_pcr_cboe)
        ref = pcr_total or pcr_equity
        if   ref and ref > 1.2:  señal = "alcista_contrario"; desc = f"PCR={ref} — miedo extremo, señal contraria alcista"
        elif ref and ref > 1.0:  señal = "precaucion";        desc = f"PCR={ref} — elevado, precaución"
        elif ref and ref < 0.6:  señal = "bajista_contrario"; desc = f"PCR={ref} — euforia, señal contraria bajista"
        elif ref and ref < 0.75: señal = "precaucion_alcista";desc = f"PCR={ref} — bajo, complacencia moderada"
        else:                    señal = "neutro";            desc = f"PCR={ref} — rango normal" if ref else "PCR no disponible"

        log.info(f"  [PCR-TXT] OK — total={pcr_total} equity={pcr_equity} index={pcr_index} | {señal.upper()} | fecha={fecha_str}")

        return {
            "total":    pcr_total,
            "equity":   pcr_equity,
            "index":    pcr_index,
            "spx":      pcr_spx,
            "señal":    señal,
            "desc":     desc,
            "fuente":   "cboe_txt_manual",
            "fecha":    fecha_str,
            "edad_dias": edad_dias,
            "fuente_verificacion": "https://www.cboe.com/data/volatility-and-put-call-ratio-data/",
        }

    except Exception as e:
        log.warning(f"  [PCR-TXT] Error parseando PCR.txt: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  ██████╗  MÓDULO FASE 3 — PCR CBOE (Put/Call Ratio diario)
# ─────────────────────────────────────────────────────────────────────────────

def calcular_pcr_cboe(opciones_data: dict = None) -> dict:
    """
    PCR Put/Call Ratio — tres fuentes con fallback en orden de prioridad:
      0. PCR.txt descargado manualmente de CBOE  ← NUEVO (prioridad máxima)
         Guardar en C:\\Users\\m21lo\\nq-proxy\\PCR.txt
      1. CBOE CSV oficial  https://cdn.cboe.com/api/global/us_indices/daily_prices/PC_STATS.csv
         (puede dar 403 desde IPs residenciales — CBOE tiene anti-scraping)
      2. PCR calculado de la cadena de opciones QQQ (Yahoo Finance)
         Ligero sesgo hacia grandes caps tech, pero muy representativo del Nasdaq.
    Fuente verificable CBOE: https://www.cboe.com/data/volatility-and-put-call-ratio-data/
    Fuente verificable Yahoo: https://finance.yahoo.com/quote/QQQ/options/
    """
    import requests

    log.info("  [PCR] Obteniendo Put/Call Ratio...")

    # ── FUENTE 0: PCR.txt manual (mayor prioridad) ────────────────────────────
    pcr_txt = parsear_pcr_txt(BASE_DIR)
    if pcr_txt is not None:
        log.info(f"  [PCR] ✅ Fuente 0 (PCR.txt manual): total={pcr_txt.get('total')} equity={pcr_txt.get('equity')}")
        return pcr_txt

    # ── FUENTE 1: CBOE CSV oficial ────────────────────────────────────────────
    def _via_cboe():
        headers_list = [
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
             "Referer": "https://www.cboe.com/", "Accept": "text/csv,*/*"},
            {"User-Agent": "python-requests/2.31", "Accept": "*/*"},
        ]
        urls = [
            "https://cdn.cboe.com/api/global/us_indices/daily_prices/PC_STATS.csv",
            "https://www.cboe.com/data/volatility-and-put-call-ratio-data/",  # fallback página
        ]
        for url in urls[:1]:  # solo el CSV
            for hdrs in headers_list:
                try:
                    r = requests.get(url, headers=hdrs, timeout=15)
                    if r.status_code == 403:
                        continue
                    r.raise_for_status()
                    from io import StringIO
                    df = pd.read_csv(StringIO(r.text))
                    df.columns = [c.strip().strip('"').lower().replace(" ", "_").replace("/", "_") for c in df.columns]
                    df = df.dropna(how="all")
                    last_row = df.iloc[-1]

                    def get_col(row, *keys):
                        for k in keys:
                            for col in row.index:
                                if k in col:
                                    try:
                                        v = float(str(row[col]).replace('"', '').strip())
                                        if not pd.isna(v) and v > 0: return round(v, 3)
                                    except: pass
                        return None

                    pcr_equity = get_col(last_row, "equity", "eq")
                    pcr_index  = get_col(last_row, "index", "idx")
                    pcr_total  = get_col(last_row, "total", "tot", "all")
                    if pcr_total is None and pcr_equity:
                        pcr_total = pcr_equity

                    pcr_hist = []
                    for i in range(min(5, len(df))):
                        v = get_col(df.iloc[-(i+1)], "total", "tot", "equity")
                        if v: pcr_hist.append(round(v, 3))

                    log.info(f"  [PCR] CBOE CSV OK: total={pcr_total} equity={pcr_equity}")
                    return pcr_equity, pcr_index, pcr_total, pcr_hist, "cboe_csv"
                except Exception as e:
                    log.warning(f"  [PCR] CBOE {url}: {e}")
        return None, None, None, [], None

    # ── FUENTE 2: PCR de opciones QQQ (Yahoo Finance) ─────────────────────────
    def _via_yahoo_options():
        if not opciones_data or opciones_data.get("error"):
            return None, None, None, [], None
        pcr_oi  = opciones_data.get("pcrOI")
        pcr_vol = opciones_data.get("pcrVol")
        if pcr_oi is None:
            return None, None, None, [], None
        log.info(f"  [PCR] Yahoo QQQ options: PCR_OI={pcr_oi} PCR_Vol={pcr_vol}")
        # Nota: este PCR es solo de QQQ, no del mercado total
        return None, None, pcr_oi, [], "yahoo_qqq_options"

    # ── EJECUTAR ──────────────────────────────────────────────────────────────
    pcr_equity, pcr_index, pcr_total, pcr_hist, fuente = _via_cboe()
    if pcr_total is None:
        pcr_equity, pcr_index, pcr_total, pcr_hist, fuente = _via_yahoo_options()

    if pcr_total is None:
        return {
            "error": "sin_datos",
            "equity": None, "total": None,
            "señal": "neutro",
            "desc": "PCR no disponible — verificar manualmente",
            "fuente_verificacion": "https://www.cboe.com/data/volatility-and-put-call-ratio-data/",
            "fuente_alternativa":  "https://finance.yahoo.com/quote/QQQ/options/",
        }

    # Tendencia
    pcr_trend = None
    if len(pcr_hist) >= 3:
        if pcr_hist[0] > pcr_hist[1] > pcr_hist[2]:   pcr_trend = "subiendo"
        elif pcr_hist[0] < pcr_hist[1] < pcr_hist[2]: pcr_trend = "bajando"
        else:                                           pcr_trend = "lateral"

    ref = pcr_total
    if ref > 1.2:    señal = "alcista_contrario";  desc = f"PCR={ref} — miedo extremo, señal contraria alcista"
    elif ref > 1.0:  señal = "precaucion";          desc = f"PCR={ref} — elevado, precaución"
    elif ref < 0.6:  señal = "bajista_contrario";   desc = f"PCR={ref} — euforia, señal contraria bajista"
    elif ref < 0.75: señal = "precaucion_alcista";  desc = f"PCR={ref} — bajo, complacencia moderada"
    else:            señal = "neutro";              desc = f"PCR={ref} — rango normal"

    # Nota de sesgo si es fuente Yahoo
    nota_sesgo = ""
    if fuente == "yahoo_qqq_options":
        nota_sesgo = " (QQQ only — proxy Nasdaq, ligero sesgo large-cap tech)"
        desc += nota_sesgo

    log.info(f"  [PCR] total={pcr_total} | {señal.upper()} | fuente={fuente}")

    return {
        "equity":  pcr_equity,
        "index":   pcr_index,
        "total":   pcr_total,
        "trend":   pcr_trend,
        "historial": pcr_hist,
        "señal":   señal,
        "desc":    desc,
        "fuente":  fuente,
        "sesgo":   nota_sesgo.strip() if nota_sesgo else None,
        "fuente_verificacion": "https://www.cboe.com/data/volatility-and-put-call-ratio-data/",
        "fuente_alternativa":  "https://finance.yahoo.com/quote/QQQ/options/",
    }


def calcular_scores(tecnicos_ndx: dict, tecnicos_qqq: dict,
                    vix_ts: dict, giro: dict, flows: dict,
                    precios: dict, macro: dict | None = None,
                    cot: dict | None = None,
                    opciones: dict | None = None,
                    pcr: dict | None = None,
                    amplitud: dict | None = None) -> dict:
    """
    Calcula el score compuesto para cada horizonte temporal.
    v5.0: integra COT real, GEX real, PCR real y Amplitud Fase 5.
    """
    t  = tecnicos_ndx.get("d", {})
    p  = precios.get("ndx") or precios.get("qqq") or 0

    # ── Score Técnico Diario ──────────────────────────────────────────────────
    def score_tecnico():
        s = 0
        rsi = t.get("rsi14") or 50
        if 45 < rsi < 65:   s += 2
        elif rsi > 70:       s -= 1
        elif rsi < 30:       s += 1

        macd_hist = (t.get("macd") or {}).get("hist") or 0
        if macd_hist > 0:    s += 2
        elif macd_hist < 0:  s -= 2

        ema21  = t.get("ema21")
        ema50  = t.get("ema50")
        ema200 = t.get("ema200")
        if ema21:  s += 1 if p > ema21  else -1
        if ema50:  s += 1 if p > ema50  else -1
        if ema200: s += 2 if p > ema200 else -2

        stoch_k = (t.get("stoch") or {}).get("k") or 50
        if stoch_k < 20:   s += 1
        elif stoch_k > 80: s -= 1

        vol_r = t.get("volRatio5") or 1
        roc5  = t.get("roc5") or 0
        if vol_r > 1.3 and roc5 > 0:   s += 1
        elif vol_r > 1.3 and roc5 < 0: s -= 1

        return max(-10, min(10, s))

    # ── Score Macro ───────────────────────────────────────────────────────────
    def score_macro_fn():
        if macro and "score" in macro:
            return float(macro["score"])
        s = 0.0
        vix = precios.get("vix") or 20
        if vix < 16:    s += 1.5
        elif vix > 25:  s -= 1.5
        elif vix > 30:  s -= 3.0
        return max(-5, min(5, round(s, 1)))

    # ── Score COT — REAL en Fase 3 ────────────────────────────────────────────
    def score_cot_fn():
        if not cot or cot.get("error"):
            return 0.0
        s = 0.0
        señal = cot.get("señal") or "neutro"
        if señal == "bajista":       s -= 3.0
        elif señal == "bajista_mod": s -= 1.5
        elif señal == "alcista":     s += 3.0
        elif señal == "alcista_mod": s += 1.5

        # Ajuste por dealers (smart money)
        señal_d = cot.get("señalDealers") or "neutro"
        if señal_d == "acumulacion":  s += 1.5   # Smart money acumula → alcista
        elif señal_d == "distribucion": s -= 1.5  # Smart money distribuye → bajista

        # Ajuste por tendencia 4 semanas
        trend4w = cot.get("trend4w")
        if trend4w is not None:
            if trend4w > 5000:    s += 0.5   # Acumulación sostenida
            elif trend4w < -5000: s -= 0.5   # Reducción sostenida

        return max(-5, min(5, round(s, 1)))

    # ── Score VIX + GEX + PCR ─────────────────────────────────────────────────
    def score_vix_fn():
        s = 0.0
        # VIX Term Structure
        senal_vix = vix_ts.get("señal") or "neutro"
        if senal_vix == "alcista":          s += 2.0
        elif senal_vix == "bajista_fuerte": s -= 3.0
        elif senal_vix == "bajista":        s -= 1.5

        # GEX real (de opciones)
        if opciones and not opciones.get("error"):
            gex = opciones.get("gex") or {}
            gex_val = gex.get("valor") or 0
            s += gex_val * 0.4       # Ponderar GEX en score VIX
            if gex.get("trampa"):
                s -= 1.5             # Trampa alcista: penalizar

            # Max Pain del primer vencimiento
            v1 = opciones.get("v1") or {}
            mp_señal = v1.get("señal") or "neutro"
            if mp_señal == "alcista":  s += 0.5
            elif mp_señal == "bajista": s -= 0.5

        # PCR (señal contraria)
        pcr_ref = None
        if pcr and not pcr.get("error"):
            pcr_ref = pcr.get("total") or pcr.get("equity")

        if pcr_ref is not None:
            if pcr_ref > 1.2:   s += 1.5   # Miedo extremo → contrarian alcista
            elif pcr_ref > 1.0: s += 0.5
            elif pcr_ref < 0.6: s -= 1.5   # Euforia → contrarian bajista
            elif pcr_ref < 0.75: s -= 0.5

        # También usar PCR de opciones (yfinance) si CBOE no disponible
        elif opciones and not opciones.get("error"):
            pcr_oi = opciones.get("pcrOI")
            if pcr_oi is not None:
                if pcr_oi > 1.2:   s += 1.0
                elif pcr_oi < 0.6: s -= 1.0

        return max(-5, min(5, round(s, 1)))

    # ── Score Flujos ──────────────────────────────────────────────────────────
    def score_flujos():
        s = 0.0
        modo = flows.get("modo") or "neutro"
        if modo == "risk_on":         s += 2.0
        elif modo == "risk_off":      s -= 2.0
        elif modo == "vuelo_calidad": s -= 3.0
        qqq_f = (flows.get("qqq") or {}).get("señal") or "neutro"
        hyg_f = (flows.get("hyg") or {}).get("señal") or "neutro"
        if qqq_f == "entradas":                  s += 1.0
        elif qqq_f == "salidas":                 s -= 1.0
        if hyg_f in ("salidas", "salidas_mod"):  s -= 1.0
        return max(-5, min(5, round(s, 1)))

    # ── Score Giro ────────────────────────────────────────────────────────────
    def score_giro():
        sg = giro.get("señalGlobal") or "neutro"
        if sg == "techo": return -2.0
        if sg == "suelo": return  2.0
        return 0.0

    # ── Score Amplitud (Fase 5 + Fase 7 A12) ────────────────────────────────
    def score_amplitud_fn():
        if amplitud is None or amplitud.get("error"):
            return 0.0
        sa = float(amplitud.get("score_amplitud") or 0.0)
        # Fase 7 A12: NDX100 breadth
        breadth = amplitud.get("ndx100_breadth") or {}
        sa += (float(breadth.get("score") or 0.0)) * 0.3
        # Fase 7 A12: Proxy China
        china = (macro or {}).get("proxy_china") or {}
        sa += (float(china.get("score") or 0.0)) * 0.2
        return float(max(-5.0, min(5.0, round(sa, 1))))

    ST = score_tecnico()
    SM = score_macro_fn()
    SC = score_cot_fn()
    SV = score_vix_fn()
    SF = score_flujos()
    SG = score_giro()
    SA = score_amplitud_fn()

    def compuesto(wt, wm, wc, wv, wf, wg, wa=0):
        total_w = wt + wm + wc + wv + wf + wg + wa
        raw = (ST*wt + SM*wm + SC*wc + SV*wv + SF*wf + SG*wg + SA*wa) / total_w
        return round(raw, 1)

    def estado(s):
        if s >= 3:  return "alcista"
        if s <= -3: return "bajista"
        if s >= 1:  return "alcista_mod"
        if s <= -1: return "bajista_mod"
        return "neutro"

    def conf(s):
        return min(95, max(10, round(abs(s) / 10 * 100)))

    # Pesos reajustados para incluir Amplitud (Fase 5) con peso moderado
    # Peso amplitud (wa) extraido a partes iguales de tecnico y flujos
    s2d = compuesto(28, 10, 10, 23, 13, 10,  6)   # 2D: tecnico+VIX dominan
    s5d = compuesto(23, 14, 14, 18, 13,  9,  9)   # 5D: equilibrado
    s1w = compuesto(18, 19, 19, 14, 13,  9,  8)   # 1S: macro+COT dominan
    s2w = compuesto(18, 23, 23,  9, 13,  5,  9)   # 2S: macro+COT+amplitud
    s3w = compuesto(13, 28, 28,  7, 11,  5,  8)   # 3S: macro+COT fuertes
    s4w = compuesto( 8, 32, 32,  4,  9,  5, 10)   # 4W: macro+COT+amplitud

    log.info(f"  Scores componentes: T={ST:+} M={SM:+} C={SC:+} V={SV:+} F={SF:+} G={SG:+} A={SA:+}")

    return {
        "componentes": {
            "tecnico": ST, "macro": SM, "cot": SC,
            "vix": SV, "flujos": SF, "giro": SG, "amplitud": SA,
        },
        "horizontes": {
            "d2": {"score": s2d, "estado": estado(s2d), "conf": conf(s2d), "pesos": "28%T+23%V+13%F+10%G+10%M+10%C+6%A"},
            "d5": {"score": s5d, "estado": estado(s5d), "conf": conf(s5d), "pesos": "23%T+18%V+14%M+14%C+13%F+9%G+9%A"},
            "w1": {"score": s1w, "estado": estado(s1w), "conf": conf(s1w), "pesos": "19%M+19%C+18%T+14%V+13%F+9%G+8%A"},
            "w2": {"score": s2w, "estado": estado(s2w), "conf": conf(s2w), "pesos": "23%M+23%C+18%T+13%F+9%A+9%V+5%G"},
            "w3": {"score": s3w, "estado": estado(s3w), "conf": conf(s3w), "pesos": "28%M+28%C+13%T+11%F+8%A+7%V+5%G"},
            "w4": {"score": s4w, "estado": estado(s4w), "conf": conf(s4w), "pesos": "32%M+32%C+10%A+9%F+8%T+5%G+4%V"},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  EXPORT JSON
# ─────────────────────────────────────────────────────────────────────────────

def exportar_json(datos: dict) -> None:
    def serializar(obj):
        if isinstance(obj, (np.integer,)):   return int(obj)
        if isinstance(obj, (np.floating,)):
            v = float(obj)
            if v != v or v == float('inf') or v == float('-inf'): return None  # NaN/Inf → null
            return round(v, 6)
        if isinstance(obj, float):
            if obj != obj or obj == float('inf') or obj == float('-inf'): return None  # NaN/Inf → null
            return obj
        if isinstance(obj, (np.bool_,)):     return bool(obj)
        if isinstance(obj, pd.Timestamp):    return obj.isoformat()
        if isinstance(obj, (np.ndarray,)):   return obj.tolist()
        raise TypeError(f"No serializable: {type(obj)}")

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2, default=serializar)

    size_kb = JSON_PATH.stat().st_size / 1024
    log.info(f"✅ datos_radar.json exportado ({size_kb:.1f} KB) → {JSON_PATH}")


def inyectar_gex_manual(datos_json: dict) -> None:
    """
    Si en opciones._gex_manual_payload hay datos del parser local, los inyecta
    en los campos que el frontend espera para auto-rellenar:
      - datos_radar.json:  raiz.maxpain  (modulo Max Pain)
      - manengis_tactico.json: derivados.top_call_strikes / top_put_strikes /
                                vencimientos / precio_qqq
                               variables_crudas.max_pain
    De esta forma se rellenan automaticamente los inputs:
      oi-precio, oi-maxpain, oi-resist, oi-soporte, sdx-gex y
      el modulo Paredes de Opciones del Radar 2-5D.
    """
    try:
        opciones = datos_json.get("opciones") or {}
        gm = opciones.get("_gex_manual_payload")
        if not gm:
            log.info("  [INYECT] No hay gex_manual_payload — saltando inyección Max Pain/OI")
            return
        # Limpiar el payload temporal del JSON final
        opciones.pop("_gex_manual_payload", None)

        precio_actual = datos_json.get("precio", {}).get("qqq") or gm.get("precio_referencia")
        venc_prox = gm.get("vencimiento_proximo") or {}

        # ── 1. Construir datos_json.maxpain (modulo Max Pain del frontend) ──
        max_pain   = venc_prox.get("max_pain")
        dist_mp    = venc_prox.get("dist_max_pain_pct")
        expiracion = venc_prox.get("expiry")
        if max_pain is not None and precio_actual:
            if dist_mp is not None and dist_mp > 4:
                senal_mp = "acumulacion"
                desc_mp  = f"Max Pain {max_pain:.0f} (+{dist_mp:.2f}%) — gravedad atrae precio arriba"
            elif dist_mp is not None and dist_mp < -4:
                senal_mp = "distribucion"
                desc_mp  = f"Max Pain {max_pain:.0f} ({dist_mp:.2f}%) — gravedad atrae precio abajo"
            else:
                senal_mp = "neutro"
                desc_mp  = f"Max Pain {max_pain:.0f} — precio cerca, zona equilibrio"
            datos_json["maxpain"] = {
                "valor":       round(float(max_pain), 0),
                "precio":      round(float(precio_actual), 2),
                "distPct":     dist_mp,
                "expiracion":  expiracion,
                "señal":       senal_mp,
                "descripcion": desc_mp,
                "fuente":      "gex_parser_local",
            }
            log.info(f"  [INYECT] datos_radar.maxpain = {max_pain} ({dist_mp:+.2f}%) | {senal_mp}")

        # ── 2. Actualizar manengis_tactico.json (campos derivados + max_pain) ──
        manengis_path = BASE_DIR / "manengis_tactico.json"
        if manengis_path.exists():
            try:
                with open(manengis_path, "r", encoding="utf-8") as f:
                    m = json.load(f)

                # Asegurar estructura
                m.setdefault("variables_crudas", {})
                m.setdefault("derivados", {})

                # Inyectar max_pain en variables_crudas
                if max_pain is not None:
                    m["variables_crudas"]["max_pain"] = round(float(max_pain), 2)

                # Inyectar precio_qqq y vencimientos en derivados
                if precio_actual:
                    m["derivados"]["precio_qqq"] = round(float(precio_actual), 2)
                if gm.get("maxpain_por_vencimiento"):
                    m["derivados"]["vencimientos"] = list(gm["maxpain_por_vencimiento"].keys())

                # Inyectar top_call_strikes y top_put_strikes (del vencimiento proximo)
                top_calls = venc_prox.get("top_calls") or []
                top_puts  = venc_prox.get("top_puts")  or []
                if top_calls:
                    m["derivados"]["top_call_strikes"] = [
                        {"strike": float(c["strike"]), "oi": int(c["oi"]), "dist": float(c["dist"])}
                        for c in top_calls
                    ]
                if top_puts:
                    m["derivados"]["top_put_strikes"] = [
                        {"strike": float(p["strike"]), "oi": int(p["oi"]), "dist": float(p["dist"])}
                        for p in top_puts
                    ]

                # Inyectar resistencia y soporte principal
                if venc_prox.get("resistencia_principal"):
                    m["derivados"]["resistencia_principal"] = venc_prox["resistencia_principal"]
                if venc_prox.get("soporte_principal"):
                    m["derivados"]["soporte_principal"] = venc_prox["soporte_principal"]
                if venc_prox.get("rango_semana"):
                    m["derivados"]["rango_semana"] = venc_prox["rango_semana"]

                # ── Inyectar PCR CBOE en manengis_tactico.json ──────────────
                # Lee pcr_data que fue calculado por calcular_pcr_cboe()
                # (con prioridad: PCR.txt > CBOE CSV > Yahoo Options)
                # El frontend Táctico busca data.pcr.{equity,total,index,spx}
                pcr_path = BASE_DIR / "PCR.txt"
                pcr_inyectado = parsear_pcr_txt(BASE_DIR)
                # Si no hay PCR.txt, intentar leer del datos_radar.json ya generado
                if pcr_inyectado is None:
                    radar_path = BASE_DIR / "datos_radar.json"
                    if radar_path.exists():
                        try:
                            with open(radar_path, "r", encoding="utf-8") as _rf:
                                _rd = json.load(_rf)
                            _pcr_rd = _rd.get("pcr") or {}
                            if _pcr_rd and not _pcr_rd.get("error"):
                                pcr_inyectado = {
                                    "total":  _pcr_rd.get("total"),
                                    "equity": _pcr_rd.get("equity"),
                                    "index":  _pcr_rd.get("index"),
                                    "spx":    _pcr_rd.get("spx"),
                                    "señal":  _pcr_rd.get("señal"),
                                    "fecha":  _pcr_rd.get("fecha"),
                                    "fuente": _pcr_rd.get("fuente"),
                                }
                        except Exception:
                            pass

                if pcr_inyectado and any(pcr_inyectado.get(k) for k in ("total", "equity")):
                    m["pcr"] = {
                        "equity": pcr_inyectado.get("equity"),
                        "total":  pcr_inyectado.get("total"),
                        "index":  pcr_inyectado.get("index"),
                        "spx":    pcr_inyectado.get("spx"),
                        "señal":  pcr_inyectado.get("señal"),
                        "fecha":  pcr_inyectado.get("fecha"),
                        "fuente": pcr_inyectado.get("fuente", "cboe_txt_manual"),
                    }
                    log.info(f"  [INYECT] manengis_tactico.json pcr inyectado: equity={m['pcr']['equity']} total={m['pcr']['total']} fecha={m['pcr']['fecha']}")

                # ── Inyectar vixTermStructure con vx1/vx2 de VIX.txt ────────────
                # El frontend Táctico busca data.vixTermStructure.{spot, vx1, vx2}
                # parsear_vix_ts_txt lee VIX.txt con los futuros reales de Cboe
                vts_inyectado = parsear_vix_ts_txt(BASE_DIR)
                if vts_inyectado is not None:
                    m["vixTermStructure"] = {
                        "spot":           vts_inyectado.get("spot"),
                        "vx1":            (vts_inyectado.get("front_month") or {}).get("precio"),
                        "vx2":            (vts_inyectado.get("second_month") or {}).get("precio"),
                        "vx1_symbol":     (vts_inyectado.get("front_month") or {}).get("symbol"),
                        "vx2_symbol":     (vts_inyectado.get("second_month") or {}).get("symbol"),
                        "vx1_expiry":     (vts_inyectado.get("front_month") or {}).get("expiry"),
                        "spread1":        vts_inyectado.get("spread1"),
                        "spread1Pct":     vts_inyectado.get("spread1Pct"),
                        "backwardation":  vts_inyectado.get("backwardation"),
                        "slope_1m2m":     vts_inyectado.get("slope_1m2m"),
                        "señal":          vts_inyectado.get("señal"),
                        "desc":           vts_inyectado.get("desc"),
                        "fuente":         "vix_txt_manual",
                        "usando_settlement": vts_inyectado.get("usando_settlement", False),
                    }
                    log.info(
                        f"  [INYECT] manengis_tactico.json vixTermStructure inyectado: "
                        f"spot={m['vixTermStructure']['spot']} "
                        f"vx1={m['vixTermStructure']['vx1']} vx2={m['vixTermStructure']['vx2']}"
                    )

                # Guardar manengis_tactico.json actualizado
                # IMPORTANTE: usar allow_nan=False para que NaN/Inf exploten antes
                # de escribir JSON inválido. Primero sanitizamos con json.dumps
                # pasando por el serializador personalizado que convierte NaN → null.
                import math
                def _sanitizar_nan(obj):
                    """Convierte recursivamente NaN/Inf a None para JSON válido."""
                    if isinstance(obj, float):
                        if math.isnan(obj) or math.isinf(obj): return None
                        return obj
                    if isinstance(obj, dict):
                        return {k: _sanitizar_nan(v) for k, v in obj.items()}
                    if isinstance(obj, list):
                        return [_sanitizar_nan(v) for v in obj]
                    return obj

                m_limpio = _sanitizar_nan(m)
                with open(manengis_path, "w", encoding="utf-8") as f:
                    json.dump(m_limpio, f, ensure_ascii=False, indent=2)
                log.info(f"  [INYECT] manengis_tactico.json actualizado | top_calls={len(top_calls)} | top_puts={len(top_puts)}")
            except Exception as _e:
                log.warning(f"  [INYECT] No se pudo actualizar manengis_tactico.json: {_e}")
        else:
            log.info(f"  [INYECT] manengis_tactico.json no existe en {manengis_path} — saltando")

    except Exception as e:
        log.warning(f"  [INYECT] Error inyectando gex_manual: {e}")



# ─────────────────────────────────────────────────────────────────────────────
#  GIT AUTO-PUSH
# ─────────────────────────────────────────────────────────────────────────────

def git_push() -> bool:
    log.info("📤 Git: iniciando push automático...")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = (
        f"Actualización automatizada del radar - {timestamp} - "
        "Sistema Cuantitativo Avanzado con Histórico 2000 e Incremental Diario"
    )

    comandos = [
        ["git", "-C", str(BASE_DIR), "add", "datos_radar.json", "manengis_tactico.json"],
        ["git", "-C", str(BASE_DIR), "commit", "-m", commit_msg],
        ["git", "-C", str(BASE_DIR), "push", "origin", "main"],
    ]

    for cmd in comandos:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                log.info("  Git: nada que commitear (JSON sin cambios)")
                return True
            log.error(f"  Git error '{' '.join(cmd[:3])}': {result.stderr.strip()}")
            return False
        else:
            log.info(f"  ✓ {' '.join(cmd[:3])}")

    log.info("✅ Push completado correctamente")
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 5 — AMPLITUD DE MERCADO, ESTACIONALIDAD Y KELLY SIZING
#  Versión: 5.0-fase5
# ─────────────────────────────────────────────────────────────────────────────

def calcular_amplitud_mercado(df: "pd.DataFrame", tecnicos_ndx,
                               vix_ts: dict, precios: dict) -> dict:
    """
    Modulo de Fase 5: Amplitud de Mercado + Estacionalidad + Kelly Sizing.

    Calcula:
      1. Ratio Cobre/Oro  -> indicador macro lider de riesgo industrial
      2. Z-Score QQQ vs SMA200  -> agotamiento o sobreextension estadistica
      3. Sesgo estacional calendario  -> Window Dressing, Sell in May, etc.
      4. Factor de exposicion recomendado (Kelly simplificado x VIX scalar)
      5. score_amplitud  -> valor -5 a +5 que se integra en calcular_scores()
    """
    resultado_default = {
        "ratio_cobre_oro":               None,
        "tendencia_cobre_oro":           "neutro",
        "señal_cobre_oro":               "neutro",
        "zscore_qqq_sma200":             None,
        "señal_zscore":                  "normal",
        "sesgo_estacional":              0,
        "descripcion_estacional":        "Sin datos de estacionalidad",
        "factor_exposicion_recomendado": 1.0,
        "kelly_bruto":                   0.5,
        "vix_scalar":                    1.0,
        "score_amplitud":                0,
        "fuente":                        "fase5_amplitud_v5",
        "error":                         None,
    }

    try:
        import yfinance as yf

        # ── 1. RATIO COBRE / ORO ────────────────────────────────────────────
        ratio_cobre_oro = None
        tend_cobre_oro  = "neutro"
        señal_cobre_oro = "neutro"

        try:
            # Nombres exactos de columna según dict SIMBOLOS:
            # KEY "HG" → "HG_close" | KEY "GC" → "GC_close" | KEY "GLD" → "GLD_close"
            # El historico_maestro.csv usa {KEY}_close, no el ticker yahoo
            CANDIDATOS_HG = ["HG_close", "HG_Close"]
            CANDIDATOS_GC = ["GC_close", "GC_Close", "GLD_close", "GLD_Close"]

            hg_col = None
            gc_col = None

            # Búsqueda con nombres exactos primero
            df_cols = list(df.columns)
            for c in CANDIDATOS_HG:
                if c in df_cols:
                    hg_col = df[c].dropna()
                    break

            for c in CANDIDATOS_GC:
                if c in df_cols:
                    gc_col = df[c].dropna()
                    break

            # Si no se encontraron por nombre exacto, búsqueda flexible (sin depender de orden)
            if hg_col is None or len(hg_col) < 5:
                for col in df_cols:
                    cu = col.upper()
                    if cu.startswith("HG") and cu.endswith("CLOSE"):
                        hg_col = df[col].dropna()
                        break

            if gc_col is None or len(gc_col) < 5:
                for col in df_cols:
                    cu = col.upper()
                    if (cu.startswith("GC") or cu.startswith("GLD")) and cu.endswith("CLOSE"):
                        gc_col = df[col].dropna()
                        break

            # Fallback a Yahoo Finance solo si el CSV realmente no tiene los datos
            if hg_col is None or len(hg_col) < 10:
                log.info("  [Fase5] HG_close no en CSV — descargando HG=F desde Yahoo...")
                hg_raw = yf.download("HG=F", period="6mo", progress=False, auto_adjust=True)
                if not hg_raw.empty:
                    if isinstance(hg_raw.columns, pd.MultiIndex):
                        hg_raw.columns = [c[0] for c in hg_raw.columns]
                    hg_col = hg_raw["Close"].dropna()

            if gc_col is None or len(gc_col) < 10:
                log.info("  [Fase5] GC_close no en CSV — descargando GC=F desde Yahoo...")
                gc_raw = yf.download("GC=F", period="6mo", progress=False, auto_adjust=True)
                if not gc_raw.empty:
                    if isinstance(gc_raw.columns, pd.MultiIndex):
                        gc_raw.columns = [c[0] for c in gc_raw.columns]
                    gc_col = gc_raw["Close"].dropna()

            log.info("  [Fase5] HG filas=" + str(len(hg_col) if hg_col is not None else 0) +
                     " | GC filas=" + str(len(gc_col) if gc_col is not None else 0))

            if hg_col is not None and gc_col is not None and len(hg_col) >= 5 and len(gc_col) >= 5:
                hg_arr = np.array(hg_col.tail(60).values, dtype=float)
                gc_arr = np.array(gc_col.tail(60).values, dtype=float)
                n = min(len(hg_arr), len(gc_arr))
                ratio_arr  = np.where(gc_arr[-n:] > 0, hg_arr[-n:] / gc_arr[-n:], np.nan)
                ratio_clean = ratio_arr[~np.isnan(ratio_arr)]

                if len(ratio_clean) >= 5:
                    ratio_cobre_oro = round(float(ratio_clean[-1]), 6)
                    ma5  = float(np.mean(ratio_clean[-5:]))
                    ma20 = float(np.mean(ratio_clean[-20:])) if len(ratio_clean) >= 20 else ma5
                    if ma5 > ma20 * 1.005:
                        tend_cobre_oro  = "up"
                        señal_cobre_oro = "risk_on"
                    elif ma5 < ma20 * 0.995:
                        tend_cobre_oro  = "down"
                        señal_cobre_oro = "risk_off"
                    else:
                        tend_cobre_oro  = "lateral"
                        señal_cobre_oro = "neutro"
                    log.info("  [Fase5] Ratio Cobre/Oro=" + str(ratio_cobre_oro) +
                             " tend=" + tend_cobre_oro + " señal=" + señal_cobre_oro)
                else:
                    log.warning("  [Fase5] Ratio Cobre/Oro: datos insuficientes tras limpiar NaN (" +
                                str(len(ratio_clean)) + " valores)")
            else:
                log.warning("  [Fase5] Ratio Cobre/Oro: no hay datos suficientes de HG o GC")

        except Exception as e_cobre:
            log.warning("  [Fase5] Cobre/Oro fallo: " + str(e_cobre))

        # ── 2. Z-SCORE QQQ vs SMA200 ────────────────────────────────────────
        zscore_qqq_sma200 = None
        señal_zscore      = "normal"

        try:
            qqq_col = None
            for col in df.columns:
                if "QQQ" in col.upper() and "CLOSE" in col.upper():
                    qqq_col = df[col].dropna()
                    break

            if qqq_col is None or len(qqq_col) < 200:
                log.info("  [Fase5] Descargando QQQ para Z-Score SMA200...")
                qqq_raw = yf.download("QQQ", period="2y", progress=False, auto_adjust=True)
                if not qqq_raw.empty:
                    if isinstance(qqq_raw.columns, pd.MultiIndex):
                        qqq_raw.columns = [c[0] for c in qqq_raw.columns]
                    qqq_col = qqq_raw["Close"].dropna()

            if qqq_col is not None and len(qqq_col) >= 210:
                qqq_s    = pd.Series(np.array(qqq_col.values, dtype=float))
                sma200   = qqq_s.rolling(200).mean()
                dist_pct = ((qqq_s - sma200) / sma200.replace(0, np.nan)) * 100
                roll_mean = dist_pct.rolling(252).mean()
                roll_std  = dist_pct.rolling(252).std().replace(0, np.nan)
                zscore_s  = (dist_pct - roll_mean) / roll_std
                zscore_clean = zscore_s.dropna()

                if len(zscore_clean) > 0:
                    zscore_qqq_sma200 = round(float(zscore_clean.iloc[-1]), 3)
                    if zscore_qqq_sma200 > 2.0:
                        señal_zscore = "sobreextendido"
                    elif zscore_qqq_sma200 > 1.5:
                        señal_zscore = "elevado"
                    elif zscore_qqq_sma200 < -2.0:
                        señal_zscore = "sobreventa"
                    elif zscore_qqq_sma200 < -1.5:
                        señal_zscore = "deprimido"
                    else:
                        señal_zscore = "normal"
                    log.info("  [Fase5] Z-Score QQQ/SMA200=" + str(zscore_qqq_sma200) + " señal=" + señal_zscore)

        except Exception as e_z:
            log.warning("  [Fase5] Z-Score QQQ/SMA200 fallo: " + str(e_z))

        # ── 3. SESGO ESTACIONAL CALENDARIO ──────────────────────────────────
        sesgo_estacional = 0
        desc_est_parts   = []

        try:
            hoy  = datetime.now()
            mes  = hoy.month
            dia  = hoy.day
            dow  = hoy.weekday()   # 0=lunes, 4=viernes

            # Efecto enero
            if mes == 1 and dia <= 15:
                sesgo_estacional += 2
                desc_est_parts.append("Efecto enero (+2): compras institucionales inicio de año")

            # Rally navideno
            if mes == 12 and dia >= 15:
                sesgo_estacional += 2
                desc_est_parts.append("Rally navideno (+2): sesgo alcista historico diciembre")

            # Sell in May
            if mes == 5:
                sesgo_estacional -= 1
                desc_est_parts.append("Sell in May (-1): inicio periodo estacionalmente debil")
            elif mes in (6, 7, 8):
                sesgo_estacional -= 1
                desc_est_parts.append("Verano debil (-1): volumen bajo, menor liquidez institucional")
            elif mes == 9:
                sesgo_estacional -= 2
                desc_est_parts.append("Septiembre (-2): mes historicamente mas debil para el NASDAQ")

            # Octubre reset
            if mes == 10:
                sesgo_estacional += 1
                desc_est_parts.append("Octubre (+1): frecuentemente marca suelo tras septiembre")

            # Window Dressing (fin de trimestre)
            meses_fin_trim = {3, 6, 9, 12}
            if mes in meses_fin_trim and dia >= 26 and dow < 5:
                sesgo_estacional += 1
                desc_est_parts.append("Window Dressing (+1): fin de trimestre, rebalanceo institucional posible")

            # Efecto inicio de mes
            if dia <= 5 and dow < 5:
                sesgo_estacional += 1
                desc_est_parts.append("Inicio de mes (+1): flujos automaticos fondos de pensiones e indexados")

            # Triple witching (3ra semana de meses de vencimiento trimestral)
            if mes in meses_fin_trim and dow == 4 and 15 <= dia <= 21:
                sesgo_estacional -= 1
                desc_est_parts.append("Triple witching (-1): presion de cobertura por vencimientos trimestrales")

            sesgo_estacional = max(-3, min(3, sesgo_estacional))

            if not desc_est_parts:
                desc_est_parts.append("Sin evento estacional relevante esta semana")

            desc_estacional = " | ".join(desc_est_parts)
            log.info("  [Fase5] Sesgo estacional=" + str(sesgo_estacional) + " | " + desc_est_parts[0])

        except Exception as e_est:
            log.warning("  [Fase5] Estacionalidad fallo: " + str(e_est))
            desc_estacional = "Error calculando estacionalidad"

        # ── 4. KELLY SIMPLIFICADO x VIX SCALAR ──────────────────────────────
        factor_exposicion = 1.0
        kelly_bruto       = 0.5
        vix_scalar        = 1.0

        try:
            qqq_hist = None
            for col in df.columns:
                if "QQQ" in col.upper() and "CLOSE" in col.upper():
                    qqq_hist = df[col].dropna()
                    break

            if qqq_hist is not None and len(qqq_hist) >= 60:
                qqq_s  = pd.Series(np.array(qqq_hist.values[-252:], dtype=float))
                ret5d  = qqq_s.pct_change(5).dropna() * 100
                wins   = ret5d[ret5d > 0]
                losses = ret5d[ret5d < 0]

                if len(wins) > 5 and len(losses) > 5:
                    win_rate  = len(wins) / len(ret5d)
                    loss_rate = 1.0 - win_rate
                    avg_win   = float(wins.mean())
                    avg_loss  = abs(float(losses.mean()))

                    if avg_win > 0:
                        kelly_bruto = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
                        kelly_bruto = max(-0.5, min(1.0, round(float(kelly_bruto), 4)))
                    else:
                        kelly_bruto = 0.25

                    log.info("  [Fase5] Kelly: win_rate=" + str(round(win_rate, 4)) + " kelly_bruto=" + str(kelly_bruto))
                else:
                    kelly_bruto = 0.35

            # VIX Scalar
            vix_actual = precios.get("vix") or vix_ts.get("spot") or 20
            if vix_actual and float(vix_actual) > 0:
                vix_scalar = max(0.3, min(1.5, round(20.0 / float(vix_actual), 4)))

            # Factor final (Kelly x VIX + bonus estacional)
            sesgo_bonus   = sesgo_estacional * 0.05
            factor_raw    = kelly_bruto * vix_scalar + sesgo_bonus
            factor_exposicion = round(max(0.0, min(1.5, float(factor_raw))), 4)
            log.info("  [Fase5] VIX_scalar=" + str(vix_scalar) + " factor_exposicion=" + str(factor_exposicion))

        except Exception as e_kelly:
            log.warning("  [Fase5] Kelly sizing fallo: " + str(e_kelly))

        # ── 5. SCORE AMPLITUD COMPUESTO ──────────────────────────────────────
        score_amp = 0.0

        if señal_cobre_oro == "risk_on":
            score_amp += 1.5
        elif señal_cobre_oro == "risk_off":
            score_amp -= 1.5

        if señal_zscore == "sobreextendido":
            score_amp -= 2.0
        elif señal_zscore == "elevado":
            score_amp -= 0.5
        elif señal_zscore == "sobreventa":
            score_amp += 2.0
        elif señal_zscore == "deprimido":
            score_amp += 0.5

        score_amp += sesgo_estacional * 0.5

        if factor_exposicion > 1.0:
            score_amp += 0.5
        elif factor_exposicion < 0.5:
            score_amp -= 0.5

        score_amp = round(max(-5.0, min(5.0, score_amp)), 1)
        log.info("  [Fase5] Score amplitud: " + str(score_amp))

        return {
            "ratio_cobre_oro":               ratio_cobre_oro,
            "tendencia_cobre_oro":           tend_cobre_oro,
            "señal_cobre_oro":               señal_cobre_oro,
            "zscore_qqq_sma200":             zscore_qqq_sma200,
            "señal_zscore":                  señal_zscore,
            "sesgo_estacional":              sesgo_estacional,
            "descripcion_estacional":        desc_estacional,
            "factor_exposicion_recomendado": factor_exposicion,
            "kelly_bruto":                   kelly_bruto,
            "vix_scalar":                    vix_scalar,
            "score_amplitud":                score_amp,
            "fuente":                        "fase5_amplitud_v5",
            "error":                         None,
        }

    except Exception as e:
        log.error("  [Fase5] calcular_amplitud_mercado FALLO TOTAL: " + str(e))
        import traceback
        log.error(traceback.format_exc())
        resultado_default["error"] = str(e)
        return resultado_default


# ─────────────────────────────────────────────────────────────────────────────
#  FASE 4 — MARKET REGIME MATCHING (Crisis Fingerprint Engine)
#  Versión: 4.0-fase4
#  Detecta similitud entre el estado actual del mercado y los patrones
#  previos a correcciones históricas desde el año 2000.
# ─────────────────────────────────────────────────────────────────────────────

# ── Catálogo de ventanas etiquetadas ─────────────────────────────────────────
# Cada entrada define una ventana de SETUP (días PREVIOS al evento),
# no el evento mismo. Así capturamos la firma pre-colapso.
#
# ESCENARIOS:
#   A) micro_3pct      — Micro-retracción (2-3%): ajuste técnico saludable
#   B) tecnica_7pct    — Corrección técnica (5-7%): testeo soportes intermedios
#   C) macro_15pct     — Corrección macro/geo (10-15%): aranceles, DXY fuerte
#   D) bajista_25pct   — Mercado bajista cíclico (20-25%): 2022 drenaje liquidez
#   E) cisne_negro_30pct — Cisne Negro (+30%): obligatorio Punto Com 2000, 2008, COVID 2020
# ─────────────────────────────────────────────────────────────────────────────

CRISIS_LABELS = {
    # ── E) CISNES NEGROS ── (obligatorio por especificación)
    "cisne_negro_30pct": [
        # Burbuja Punto Com 2000 (setup dic-1999 a mar-2000)
        ("1999-12-01", "2000-03-10"),
        # Segunda ola bajista Punto Com 2001 (NASDAQ −40% adicional)
        ("2001-03-01", "2001-09-15"),
        # Crisis Financiera 2008 (setup verano 2007 a oct-2008)
        ("2007-06-01", "2008-10-10"),
        # COVID Crash marzo 2020
        ("2020-01-15", "2020-03-23"),
    ],
    # ── D) MERCADO BAJISTA CÍCLICO ──
    "bajista_25pct": [
        # 2022: drenaje Fed — inflación/tipos (QQQ −35%)
        ("2021-11-01", "2022-06-16"),
        # 2011: crisis deuda europea + downgrade EEUU
        ("2011-04-01", "2011-10-04"),
        # 2015-2016: mini-crash China + Fed hike
        ("2015-06-01", "2016-02-11"),
        # 2018: Q4 sell-off acelerado (QQQ −22%)
        ("2018-09-15", "2018-12-26"),
    ],
    # ── C) CORRECCIÓN MACRO/GEOPOLÍTICA ──
    "macro_15pct": [
        # 2010: Flash Crash + crisis Grecia
        ("2010-03-01", "2010-07-02"),
        # 2013: Taper Tantrum (Bernanke)
        ("2013-05-01", "2013-06-24"),
        # 2014: Geopolítica Ucrania
        ("2014-07-01", "2014-10-15"),
        # 2019: Aranceles China trade war
        ("2019-04-15", "2019-06-03"),
        # 2020 ago-sep: corrección post-rally COVID
        ("2020-08-01", "2020-09-24"),
        # 2023: Banking crisis (SVB) — corrección régimen
        ("2023-02-01", "2023-03-24"),
    ],
    # ── B) CORRECCIÓN TÉCNICA ──
    "tecnica_7pct": [
        # 2012: miedo fiscal cliff
        ("2012-09-01", "2012-11-16"),
        # 2014: corrección técnica septiembre
        ("2014-08-01", "2014-09-17"),
        # 2019: mayo (aranceles iniciales, −8%)
        ("2019-04-25", "2019-06-03"),
        # 2021: sept corrección técnica
        ("2021-08-15", "2021-10-04"),
        # 2023: julio-oct corrección tasas
        ("2023-07-18", "2023-10-27"),
        # 2024: julio rotation crash (mega-caps)
        ("2024-06-15", "2024-08-05"),
    ],
    # ── A) MICRO-RETRACCIÓN ──
    "micro_3pct": [
        # 2017: correcciones menores en bull market
        ("2017-02-01", "2017-02-28"),
        ("2017-08-01", "2017-08-22"),
        # 2019: pullback técnico
        ("2019-07-01", "2019-08-06"),
        # 2021: varios pullbacks
        ("2021-02-01", "2021-03-08"),
        # 2024: micro correcciones
        ("2024-01-15", "2024-01-19"),
        ("2024-04-01", "2024-04-19"),
    ],
}


def _safe_col(df: pd.DataFrame, *candidates) -> pd.Series | None:
    """Devuelve la primera columna existente entre candidatos. Case-insensitive."""
    df_cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        real = df_cols_lower.get(cand.lower())
        if real:
            return df[real]
    return None


def construir_matriz_firmas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Construye la matriz de features diarios desde historico_maestro.csv.
    Devuelve DataFrame con índice DatetimeIndex y columnas de features normalizadas.
    """
    try:
        ndx = _safe_col(df, "NDX_close", "NDX_Close")
        vix = _safe_col(df, "VIX_close", "VIX_Close")
        qqq = _safe_col(df, "QQQ_close", "QQQ_Close")
        tlt = _safe_col(df, "TLT_close", "TLT_Close")
        hyg = _safe_col(df, "HYG_close", "HYG_Close")
        gld = _safe_col(df, "GLD_close", "GLD_Close")

        features = pd.DataFrame(index=df.index)

        # ── Momentum NDX ──
        if ndx is not None:
            features["roc5_ndx"]  = ndx.pct_change(5)  * 100
            features["roc10_ndx"] = ndx.pct_change(10) * 100
            features["roc20_ndx"] = ndx.pct_change(20) * 100
            # Pendiente EMA50 (normalizada)
            ema50_ndx = ndx.ewm(span=50, adjust=False).mean()
            features["ema50_slope"] = ema50_ndx.pct_change(5) * 100
            # RSI14 en NDX
            delta = ndx.diff()
            gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
            rs = gain / loss.replace(0, np.nan)
            features["rsi14_ndx"] = 100 - (100 / (1 + rs))
            # Bollinger %B
            sma20 = ndx.rolling(20).mean()
            std20 = ndx.rolling(20).std()
            lower_bb = sma20 - 2 * std20
            upper_bb = sma20 + 2 * std20
            band_range = (upper_bb - lower_bb).replace(0, np.nan)
            features["bb_pct_ndx"] = ((ndx - lower_bb) / band_range) * 100
            # MACD histograma
            ema12 = ndx.ewm(span=12, adjust=False).mean()
            ema26 = ndx.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            features["macd_hist_ndx"] = macd_line - signal_line
            # Distancia a SMA200 (z-score proxy)
            sma200 = ndx.rolling(200).mean()
            features["dist_sma200"] = ((ndx - sma200) / sma200) * 100

        # ── VIX ──
        if vix is not None:
            features["vix_nivel"] = vix
            features["roc5_vix"]  = vix.pct_change(5) * 100
            features["roc20_vix"] = vix.pct_change(20) * 100
            # VIX z-score rolling 252d
            vix_roll_mean = vix.rolling(252).mean()
            vix_roll_std  = vix.rolling(252).std().replace(0, np.nan)
            features["vix_zscore"] = (vix - vix_roll_mean) / vix_roll_std

        # ── Risk-Off indicators ──
        if tlt is not None:
            features["roc10_tlt"] = tlt.pct_change(10) * 100
            features["roc20_tlt"] = tlt.pct_change(20) * 100
        if hyg is not None:
            features["roc5_hyg"]  = hyg.pct_change(5) * 100
            features["roc10_hyg"] = hyg.pct_change(10) * 100
        if gld is not None:
            features["roc5_gld"]  = gld.pct_change(5) * 100
        if qqq is not None:
            features["roc20_qqq"] = qqq.pct_change(20) * 100

        # ── Volatilidad realizada ──
        if ndx is not None:
            features["vol_realizada_20d"] = ndx.pct_change().rolling(20).std() * np.sqrt(252) * 100

        # Eliminar filas con demasiados NaN
        features = features.dropna(thresh=int(len(features.columns) * 0.6))

        return features

    except Exception as e:
        log.error(f"  ✗ [Fase4] Error construyendo matriz de firmas: {e}")
        return pd.DataFrame()


def normalizar_features_zscore(features: pd.DataFrame,
                                 window: int = 504) -> pd.DataFrame:
    """
    Aplica Z-score rolling (ventana = window días ≈ 2 años) para eliminar
    el efecto del nivel absoluto y comparar patrones de forma robusta.
    """
    normalized = pd.DataFrame(index=features.index)
    for col in features.columns:
        series = features[col]
        roll_mean = series.rolling(window=window, min_periods=60).mean()
        roll_std  = series.rolling(window=window, min_periods=60).std().replace(0, np.nan)
        normalized[col] = (series - roll_mean) / roll_std
    # Limitar outliers extremos (clamp a ±4σ)
    normalized = normalized.clip(-4, 4)
    return normalized


def extraer_firma_ventana(features_norm: pd.DataFrame,
                           fecha_inicio: str,
                           fecha_fin:    str) -> np.ndarray | None:
    """
    Extrae el vector de firma promedio de una ventana temporal.
    Devuelve ndarray de shape (n_features,) o None si no hay datos.
    """
    try:
        mask = (features_norm.index >= pd.Timestamp(fecha_inicio)) & \
               (features_norm.index <= pd.Timestamp(fecha_fin))
        ventana = features_norm.loc[mask]
        if len(ventana) < 3:
            return None
        vec = ventana.mean().values
        if np.all(np.isnan(vec)):
            return None
        return vec
    except Exception:
        return None


def similitud_coseno(v1: np.ndarray, v2: np.ndarray) -> float:
    """Similitud coseno entre dos vectores. Devuelve -1 a 1."""
    mask = ~(np.isnan(v1) | np.isnan(v2))
    if mask.sum() < 3:
        return 0.0
    a, b = v1[mask], v2[mask]
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.clip(np.dot(a, b) / (norm_a * norm_b), -1, 1))


def distancia_euclidiana_norm(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Distancia euclidiana normalizada entre dos vectores.
    Devuelve similitud 0-1 (1 = idéntico).
    """
    mask = ~(np.isnan(v1) | np.isnan(v2))
    if mask.sum() < 3:
        return 0.0
    a, b = v1[mask], v2[mask]
    dist = np.linalg.norm(a - b)
    max_dist = np.sqrt(len(a)) * 8.0
    sim = 1.0 - (dist / max_dist)
    return float(np.clip(sim, 0, 1))


def calcular_similitud_escenario(firma_actual: np.ndarray,
                                   firmas_historicas: list) -> float:
    """
    Calcula la similitud máxima y promedio entre la firma actual
    y una lista de firmas históricas de un mismo escenario.
    Devuelve porcentaje 0-100.
    """
    if not firmas_historicas or firma_actual is None:
        return 0

    similitudes = []
    for fh in firmas_historicas:
        if fh is None:
            continue
        cos = similitud_coseno(firma_actual, fh)
        euc = distancia_euclidiana_norm(firma_actual, fh)
        cos_norm = (cos + 1) / 2          # Normalizar (-1,1) → (0,1)
        sim_combinada = 0.70 * cos_norm + 0.30 * euc
        similitudes.append(sim_combinada)

    if not similitudes:
        return 0

    similitudes_sorted = sorted(similitudes, reverse=True)
    top2_mean  = np.mean(similitudes_sorted[:2]) if len(similitudes_sorted) >= 2 else similitudes_sorted[0]
    resto_mean = np.mean(similitudes_sorted[2:]) if len(similitudes_sorted) > 2 else top2_mean
    score_final = 0.60 * top2_mean + 0.40 * resto_mean

    raw_pct = score_final * 100
    adjusted = 50 + (raw_pct - 50) * 1.4
    return int(np.clip(adjusted, 0, 100))


def calcular_market_regime_matching(df: pd.DataFrame,
                                     tecnicos_ndx: dict,
                                     macro: dict | None) -> dict:
    """
    Módulo principal de Fase 4 — Market Regime Matching.
    Compara la firma actual del mercado con patrones históricos de crisis.

    Args:
        df           : historico_maestro.csv como DataFrame
        tecnicos_ndx : resultado de calcular_tecnicos(df, "NDX")
        macro        : resultado de calcular_macro_fred (puede ser None)

    Returns:
        dict con comparativa_correcciones lista para datos_radar.json
    """
    log.info("  [Fase4] Construyendo matriz de features históricos...")

    resultado_default = {
        "micro_3pct":        0,
        "tecnica_7pct":      0,
        "macro_15pct":       0,
        "bajista_25pct":     0,
        "cisne_negro_30pct": 0,
        "escenario_dominante": "indeterminado",
        "recomendacion":     "MONITOREAR SOPORTES",
        "confianza":         0,
        "detalle":           "Datos insuficientes para análisis de régimen",
        "fuente":            "market_regime_matching_v4",
    }

    try:
        if df is None or df.empty or len(df) < 400:
            log.warning("  [Fase4] Histórico insuficiente (<400 filas) — saltando MRM")
            return resultado_default

        # ── 1. Construir la matriz completa de features ───────────────────────
        features_raw = construir_matriz_firmas(df)
        if features_raw.empty or len(features_raw) < 200:
            log.warning("  [Fase4] Matriz de features vacía o insuficiente")
            return resultado_default

        log.info(f"  [Fase4] Matriz: {len(features_raw)} filas × {len(features_raw.columns)} cols")

        # ── 2. Normalización Z-score rolling ─────────────────────────────────
        features_norm = normalizar_features_zscore(features_raw, window=504)
        features_norm = features_norm.dropna(thresh=int(len(features_norm.columns) * 0.5))

        if features_norm.empty:
            log.warning("  [Fase4] No hay suficientes datos normalizados")
            return resultado_default

        # ── 3. Firma ACTUAL (últimos 10 días hábiles ≈ 2 semanas) ────────────
        firma_actual_raw = features_norm.tail(10).mean().values.copy()

        # Enriquecer con datos precisos del módulo técnico (Fase 1)
        if tecnicos_ndx and tecnicos_ndx.get("d"):
            d = tecnicos_ndx["d"]
            feature_names = list(features_norm.columns)
            overrides = {
                "rsi14_ndx":     d.get("rsi14"),
                "bb_pct_ndx":    d.get("bb", {}).get("pct"),
                "macd_hist_ndx": d.get("macd", {}).get("hist"),
                "roc5_ndx":      d.get("roc5"),
                "roc20_ndx":     d.get("roc20"),
            }
            for feat_name, val in overrides.items():
                if feat_name in feature_names and val is not None:
                    idx = feature_names.index(feat_name)
                    col_data = features_norm[feat_name].dropna()
                    if len(col_data) > 10:
                        col_mean = col_data.mean()
                        col_std  = col_data.std()
                        if col_std > 0:
                            z_val = (val - col_mean) / col_std
                            firma_actual_raw[idx] = float(np.clip(z_val, -4, 4))

        log.info(f"  [Fase4] Firma actual: {len(firma_actual_raw)} features")

        # ── 4. Extraer firmas históricas por escenario ────────────────────────
        log.info("  [Fase4] Extrayendo firmas históricas por escenario...")
        firmas_por_escenario: dict = {}

        for escenario, ventanas in CRISIS_LABELS.items():
            firmas_escenario = []
            for inicio, fin in ventanas:
                firma = extraer_firma_ventana(features_norm, inicio, fin)
                if firma is not None:
                    firmas_escenario.append(firma)
            firmas_por_escenario[escenario] = firmas_escenario
            log.info(f"  [Fase4]   {escenario}: {len(firmas_escenario)}/{len(ventanas)} ventanas válidas")

        # ── 5. Calcular similitudes ───────────────────────────────────────────
        scores_brutos: dict = {}
        for escenario, firmas in firmas_por_escenario.items():
            sim = calcular_similitud_escenario(firma_actual_raw, firmas)
            scores_brutos[escenario] = sim

        log.info(f"  [Fase4] Scores brutos: {scores_brutos}")

        # ── 6. Ajuste contextual con macro y técnicos actuales ────────────────
        scores_ajustados = dict(scores_brutos)

        # Obtener VIX actual del histórico
        vix_actual = None
        vix_col = _safe_col(df, "VIX_close", "VIX_Close")
        if vix_col is not None and len(vix_col.dropna()) > 0:
            vix_actual = float(vix_col.dropna().iloc[-1])

        # Ajuste por VIX
        if vix_actual is not None:
            if vix_actual > 35:
                scores_ajustados["cisne_negro_30pct"] = min(100, scores_ajustados["cisne_negro_30pct"] + 15)
                scores_ajustados["bajista_25pct"]     = min(100, scores_ajustados["bajista_25pct"] + 10)
            elif vix_actual > 25:
                scores_ajustados["macro_15pct"]    = min(100, scores_ajustados["macro_15pct"] + 8)
                scores_ajustados["bajista_25pct"]  = min(100, scores_ajustados["bajista_25pct"] + 5)
            elif vix_actual < 15:
                scores_ajustados["micro_3pct"]        = min(100, scores_ajustados["micro_3pct"] + 8)
                scores_ajustados["tecnica_7pct"]      = min(100, scores_ajustados["tecnica_7pct"] + 5)
                scores_ajustados["cisne_negro_30pct"] = max(0,  scores_ajustados["cisne_negro_30pct"] - 10)

        # Ajuste por curva de tipos (Fase 2)
        if macro and isinstance(macro, dict):
            curva = macro.get("curva", {})
            sp10_3m = curva.get("sp10_3m")
            if sp10_3m is not None:
                if sp10_3m < -0.5:
                    scores_ajustados["bajista_25pct"] = min(100, scores_ajustados["bajista_25pct"] + 12)
                    scores_ajustados["macro_15pct"]   = min(100, scores_ajustados["macro_15pct"] + 8)
                elif sp10_3m < 0:
                    scores_ajustados["macro_15pct"]   = min(100, scores_ajustados["macro_15pct"] + 5)
                elif sp10_3m > 1.0:
                    scores_ajustados["micro_3pct"]    = min(100, scores_ajustados["micro_3pct"] + 5)
                    scores_ajustados["bajista_25pct"] = max(0,  scores_ajustados["bajista_25pct"] - 8)

            # Ajuste por HY Credit Spread
            fred_data = macro.get("fred", {})
            hy_spread = fred_data.get("hySpread", {})
            hy_val = hy_spread.get("v") if isinstance(hy_spread, dict) else None
            if hy_val is not None:
                if hy_val > 5.5:
                    scores_ajustados["cisne_negro_30pct"] = min(100, scores_ajustados["cisne_negro_30pct"] + 12)
                    scores_ajustados["bajista_25pct"]     = min(100, scores_ajustados["bajista_25pct"] + 8)
                elif hy_val > 4.0:
                    scores_ajustados["macro_15pct"]       = min(100, scores_ajustados["macro_15pct"] + 8)
                elif hy_val < 3.0:
                    scores_ajustados["micro_3pct"]        = min(100, scores_ajustados["micro_3pct"] + 5)
                    scores_ajustados["cisne_negro_30pct"] = max(0,  scores_ajustados["cisne_negro_30pct"] - 8)

        # Ajuste por RSI diario NDX (Fase 1)
        if tecnicos_ndx and tecnicos_ndx.get("d"):
            rsi_actual = tecnicos_ndx["d"].get("rsi14")
            if rsi_actual is not None:
                if rsi_actual > 75:
                    scores_ajustados["tecnica_7pct"] = min(100, scores_ajustados["tecnica_7pct"] + 10)
                    scores_ajustados["micro_3pct"]   = min(100, scores_ajustados["micro_3pct"] + 7)
                elif rsi_actual < 30:
                    scores_ajustados["cisne_negro_30pct"] = min(100, scores_ajustados["cisne_negro_30pct"] + 8)
                    scores_ajustados["bajista_25pct"]     = min(100, scores_ajustados["bajista_25pct"] + 5)
                elif rsi_actual < 40:
                    scores_ajustados["macro_15pct"]       = min(100, scores_ajustados["macro_15pct"] + 5)

        # ── 7. Normalización final (cap 95) ───────────────────────────────────
        scores_finales = {k: int(np.clip(v, 0, 95)) for k, v in scores_ajustados.items()}

        # ── 8. Escenario dominante ────────────────────────────────────────────
        escenario_dominante = max(scores_finales, key=scores_finales.get)
        score_dominante     = scores_finales[escenario_dominante]

        sorted_scores = sorted(scores_finales.values(), reverse=True)
        confianza = int(np.clip((sorted_scores[0] - sorted_scores[1]) * 1.5, 5, 95)) if len(sorted_scores) > 1 else 50

        # ── 9. Recomendación de cartera ───────────────────────────────────────
        RECOMENDACIONES = {
            "micro_3pct":        "MANTENER/ACUMULAR",
            "tecnica_7pct":      "MONITOREAR SOPORTES",
            "macro_15pct":       "MONITOREAR SOPORTES",
            "bajista_25pct":     "REDUCIR EXPOSICION / RETIRAR DINERO A LIQUIDEZ",
            "cisne_negro_30pct": "REDUCIR EXPOSICION / RETIRAR DINERO A LIQUIDEZ",
        }
        recomendacion = RECOMENDACIONES.get(escenario_dominante, "MONITOREAR SOPORTES")

        # Override por umbrales críticos
        if scores_finales["cisne_negro_30pct"] > 65 or scores_finales["bajista_25pct"] > 70:
            recomendacion = "REDUCIR EXPOSICION / RETIRAR DINERO A LIQUIDEZ"
        elif scores_finales["macro_15pct"] > 60 or scores_finales["bajista_25pct"] > 55:
            recomendacion = "MONITOREAR SOPORTES"
        elif scores_finales["micro_3pct"] > 60 and scores_finales["bajista_25pct"] < 35:
            recomendacion = "MANTENER/ACUMULAR"

        # ── 10. Texto de detalle ──────────────────────────────────────────────
        ESCENARIO_DESC = {
            "micro_3pct":        "Micro-retracción técnica (2-3%)",
            "tecnica_7pct":      "Corrección técnica (5-7%)",
            "macro_15pct":       "Corrección macro/geopolítica (10-15%)",
            "bajista_25pct":     "Mercado bajista cíclico (20-25%)",
            "cisne_negro_30pct": "Colapso sistémico / Cisne Negro (+30%)",
        }
        desc_dom = ESCENARIO_DESC.get(escenario_dominante, escenario_dominante)
        vix_str  = f"VIX={vix_actual:.1f}" if vix_actual else "VIX=n/d"
        rsi_str  = (f"RSI={tecnicos_ndx['d']['rsi14']:.0f}"
                    if (tecnicos_ndx and tecnicos_ndx.get("d") and tecnicos_ndx["d"].get("rsi14"))
                    else "RSI=n/d")

        detalle = (
            f"Escenario dominante: {desc_dom} ({score_dominante}% similitud). "
            f"Contexto: {vix_str}, {rsi_str}. Confianza del sistema: {confianza}%. "
        )
        if scores_finales["cisne_negro_30pct"] > 50:
            detalle += "⚠ Similitud con crisis sistémicas elevada — máxima precaución. "
        if scores_finales["bajista_25pct"] > 55:
            detalle += "⚠ Patrón de drenaje de liquidez activo — reducir exposición. "
        if scores_finales["micro_3pct"] > 55 and escenario_dominante in ("micro_3pct", "tecnica_7pct"):
            detalle += "✅ Entorno compatible con corrección menor — mantener posiciones core. "

        log.info(f"  [Fase4] ✅ Dominante: {escenario_dominante} ({score_dominante}%)")
        log.info(f"  [Fase4]    Recomendación: {recomendacion}")
        log.info(f"  [Fase4]    Confianza: {confianza}%")

        return {
            "micro_3pct":         scores_finales["micro_3pct"],
            "tecnica_7pct":       scores_finales["tecnica_7pct"],
            "macro_15pct":        scores_finales["macro_15pct"],
            "bajista_25pct":      scores_finales["bajista_25pct"],
            "cisne_negro_30pct":  scores_finales["cisne_negro_30pct"],
            "escenario_dominante": escenario_dominante,
            "recomendacion":      recomendacion,
            "confianza":          confianza,
            "detalle":            detalle,
            "fuente":             "market_regime_matching_v4",
            "ts_calculo":         datetime.now().isoformat(),
        }

    except Exception as e:
        log.error(f"  ✗ [Fase4] Error en Market Regime Matching: {e}")
        import traceback
        log.error(traceback.format_exc())
        return {**resultado_default, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN — v4.0-fase4
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NQ Radar Cuantitativo v8 - Actualizador unificado (APIs + CSV local)")
    parser.add_argument("--init",     action="store_true", help="Forzar descarga historica completa desde 2000")
    parser.add_argument("--nogit",    action="store_true", help="Saltar el git push")
    parser.add_argument("--nomacro",  action="store_true", help="Saltar modulo FRED (modo offline)")
    parser.add_argument("--noderivativos", action="store_true", help="Saltar modulos COT + Opciones + PCR (APIs)")
    parser.add_argument("--noinstitucional", action="store_true", help="Saltar modulos lentos: NDX100 breadth + SEC insiders")
    parser.add_argument("--nocsv",    action="store_true", help="Saltar capa CSV local (usar solo APIs/Yahoo)")
    parser.add_argument("--solocsv",  action="store_true", help="Solo capa CSV: saltar APIs lentas (NDX100, SEC, FRED, Yahoo institucional)")
    args = parser.parse_args()

    # --solocsv implica saltar APIs lentas
    if args.solocsv:
        args.noinstitucional = True
        args.noderivativos   = True   # Las funciones online de COT/Opciones/PCR son lentas; CSV es instantaneo
        # No tocamos args.nomacro: FRED es rapido y aporta mucho. Si quieres saltarlo, anade --nomacro.

    log.info("=" * 65)
    log.info(f"NQ RADAR CUANTITATIVO v{VERSION} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 65)
    log.info(f"  CSV local: {'DESACTIVADO (--nocsv)' if args.nocsv else 'ACTIVADO (capa autoritativa)'}")
    log.info(f"  Carpeta DATOS_CSV: {DATA_CSV_DIR}")

    # ── FASE 7 A0: Estado de la sesion de mercado (NO aborta nunca) ─────────
    # Antes: si yfinance no tenia vela diaria de hoy abortabamos con sys.exit(0).
    # Eso fallaba en premercado (ejecutar antes de las 15:30 CEST) y daba el
    # falso "possibly delisted; no price data found". Ahora clasificamos el
    # estado y SIEMPRE continuamos: si no hay vela de hoy, se trabaja con la
    # ultima disponible en el historico.
    _estado_mkt = estado_sesion_mercado()
    log.info(f"  Estado mercado USA: {_estado_mkt['estado']} — {_estado_mkt['descripcion']}")
    if not _estado_mkt["ejecutar"]:
        # Caso extremadamente improbable con la politica nueva, pero lo
        # dejamos por seguridad.
        log.info("Politica de estado decide NO ejecutar. Saliendo.")
        sys.exit(0)

    # ── 1. Histórico ──────────────────────────────────────────────────────────
    log.info("\n[1/8] Cargando histórico de datos...")
    df = cargar_o_inicializar_historico(forzar_init=args.init)

    # ── 2. Indicadores técnicos ────────────────────────────────────────────────
    log.info("\n[2/8] Calculando indicadores técnicos...")
    tecnicos_ndx = calcular_tecnicos(df, "NDX")
    tecnicos_qqq = calcular_tecnicos(df, "QQQ")
    if tecnicos_ndx:
        log.info(f"  NDX: precio={tecnicos_ndx['d'].get('precio'):.2f}, RSI={tecnicos_ndx['d'].get('rsi14'):.1f}, MACD_hist={tecnicos_ndx['d'].get('macd', {}).get('hist'):.2f}")

    # ── 3. VIX Term Structure ──────────────────────────────────────────────────
    log.info("\n[3/8] VIX Term Structure...")
    vix_ts = calcular_vix_ts(df)
    log.info(f"  VIX Spot={vix_ts.get('spot')}, VIX3M={vix_ts.get('vix3m')}, Señal={vix_ts.get('señal')}")

    # ── Enriquecimiento con VIX.txt (futuros reales de Cboe) ─────────────────
    # Si VIX.txt existe en nq-proxy, parsear_vix_ts_txt() devuelve una versión
    # más completa con front/second month, curva completa y pendiente.
    # Prevalece sobre calcular_vix_ts excepto en vixPercentil (requiere histórico).
    vix_ts_txt = parsear_vix_ts_txt(BASE_DIR)
    if vix_ts_txt is not None:
        # Preservar vixPercentil del cálculo histórico si está disponible
        if vix_ts.get("vixPercentil") is not None:
            vix_ts_txt["vixPercentil"] = vix_ts["vixPercentil"]
        # Si el spot del TXT es None (raro), usar el del histórico
        if vix_ts_txt.get("spot") is None and vix_ts.get("spot") is not None:
            vix_ts_txt["spot"] = vix_ts["spot"]
        vix_ts = vix_ts_txt
        log.info(
            f"  [VIX-TXT] Enriquecido: spot={vix_ts.get('spot')} "
            f"front={vix_ts.get('front_month',{}).get('symbol')}={vix_ts.get('front_month',{}).get('precio')} "
            f"spread={vix_ts.get('spread1'):+.2f} | slope={vix_ts.get('slope_1m2m')}"
        )

    # ── 4. Giro, flujos y liquidez ────────────────────────────────────────────
    log.info("\n[4/8] Detectores de giro, flujos y liquidez...")
    giro     = detectar_giro(df, tecnicos_ndx)
    flows    = calcular_flujos(df)
    precios  = extraer_precios(df)
    liquidez = calcular_liquidez(df, tecnicos_ndx)
    log.info(f"  Giro global={giro.get('señalGlobal')}, Modo mercado={flows.get('modo')}")

    # ── 5. FASE 2: Macro FRED ─────────────────────────────────────────────────
    macro = None
    if not args.nomacro:
        log.info("\n[5/8] 🏛️  FASE 2 — Macro FRED (Liquidez, Curva, Tipos Reales, DXY)...")
        try:
            macro = calcular_macro_fred(df, precios)
            log.info(f"  Score macro FRED: {macro.get('score'):+.1f}")
            if macro.get("tiposRealesOro", {}).get("alerta"):
                log.warning(f"  ⚠️  ALERTA DRENAJE LIQUIDEZ: {macro['tiposRealesOro']['desc']}")
            curva = macro.get("curva", {})
            if curva.get("invertida3m"):
                log.warning(f"  ⚠️  CURVA INVERTIDA 10Y-3M: Spread={curva.get('sp10_3m')}%")
        except Exception as e:
            log.error(f"  ✗ Error en módulo macro FRED: {e}")
            macro = None
    else:
        log.info("\n[5/8] Módulo macro FRED saltado (--nomacro)")

    # ── 5.5 FASE 3: COT + Opciones + PCR ─────────────────────────────────────
    cot_data      = None
    opciones_data = None
    pcr_data      = None

    if not args.noderivativos:
        log.info("\n[5.5/8] 📊 FASE 3 — COT + Options QQQ + PCR CBOE...")

        # COT
        try:
            cot_data = calcular_cot()
            if not cot_data.get("error"):
                log.info(f"  ✅ COT: {cot_data.get('fecha')} | Neto={cot_data.get('neto'):+,} | {cot_data.get('señal').upper()}")
            else:
                log.warning(f"  [!] COT: {cot_data.get('error')}")
        except Exception as e:
            log.error(f"  ✗ COT falló: {e}")
            cot_data = {"error": str(e), "señal": "neutro", "desc": str(e),
                        "largos": None, "cortos": None, "neto": None,
                        "pctLargo": None, "cambioNeto": None, "trend4w": None,
                        "señalDealers": "neutro", "netoDealers": None}

        # Opciones QQQ
        try:
            opciones_data = calcular_opciones_qqq(precios)
            if not opciones_data.get("error"):
                v1 = opciones_data.get("v1") or {}
                log.info(f"  ✅ Opciones: MaxPain={v1.get('maxPain')} | GEX={opciones_data['gex']['estado']} | PCR_OI={opciones_data.get('pcrOI')}")
            else:
                log.warning(f"  [!] Opciones: {opciones_data.get('error')}")
        except Exception as e:
            log.error(f"  ✗ Opciones falló: {e}")
            opciones_data = {"error": str(e),
                             "gex": {"estado": "neutro", "valor": 0, "trampa": False, "desc": str(e)},
                             "v1": None, "v2": None, "v3": None, "pcrOI": None, "pcrVol": None}

        # PCR CBOE
        try:
            pcr_data = calcular_pcr_cboe(opciones_data)
            if not pcr_data.get("error"):
                log.info(f"  ✅ PCR CBOE: Total={pcr_data.get('total')} | Equity={pcr_data.get('equity')} | Señal={pcr_data.get('señal').upper()}")
            else:
                log.warning(f"  [!] PCR CBOE: {pcr_data.get('error')}")
        except Exception as e:
            log.error(f"  ✗ PCR CBOE falló: {e}")
            pcr_data = {"error": str(e), "equity": None, "total": None,
                        "señal": "neutro", "desc": str(e)}
    else:
        log.info("\n[5.5/8] Módulos COT+Opciones+PCR saltados (--noderivativos)")
        cot_data      = {"error": "saltado_noderivativos", "señal": "neutro",
                         "largos": None, "cortos": None, "neto": None,
                         "pctLargo": None, "cambioNeto": None, "trend4w": None,
                         "señalDealers": "neutro", "netoDealers": None, "desc": ""}
        opciones_data = {"error": "saltado_noderivativos",
                         "gex": {"estado": "neutro", "valor": 0, "trampa": False, "desc": ""}}
        pcr_data      = {"error": "saltado_noderivativos", "equity": None,
                         "total": None, "señal": "neutro", "desc": ""}

    # ═════════════════════════════════════════════════════════════════════════
    #  [5.6/8] CAPA CSV LOCAL — PREVALECE sobre las APIs anteriores
    # ═════════════════════════════════════════════════════════════════════════
    #  Aqui leemos los CSV locales (COT/CBOE/SqueezeMetrics/Barchart) y, cuando
    #  estan disponibles, SOBRESCRIBEN los datos calculados por las APIs en el
    #  bloque anterior. Si los CSV no existen, mantenemos los datos legacy
    #  (Yahoo + CFTC API) como fallback transparente.
    # ─────────────────────────────────────────────────────────────────────────
    cot_csv_data       = None
    vix_vvix_skew_data = None
    dix_gex_data       = None
    qqq_opciones_csv   = None

    if not args.nocsv:
        log.info("\n[5.6/8] CAPA CSV LOCAL (prevalece sobre APIs)...")

        # CSV-1: COT
        try:
            cot_csv_data = leer_cot_csv()
            if cot_csv_data:
                cot_data = mapear_cot_csv_al_legacy(cot_csv_data, cot_data)
                log.info(f"  [CSV] COT prevalece: fecha={cot_csv_data.get('fecha')} "
                         f"pctLargos={cot_csv_data.get('lev_pct_largos')}% "
                         f"senal={cot_csv_data.get('señal','?').upper()} "
                         f"(p{cot_csv_data.get('percentil_historico')}, "
                         f"{cot_csv_data.get('semanas_historico')}sem)")
        except Exception as e:
            log.warning(f"  [CSV] COT fallo (mantengo legacy): {e}")
            cot_csv_data = None

        # CSV-2: VIX + VVIX + SKEW
        try:
            vix_vvix_skew_data = leer_vix_vvix_skew_csv()
            if vix_vvix_skew_data:
                vix_ts = mapear_vix_csv_al_legacy(vix_vvix_skew_data, vix_ts)
                log.info(f"  [CSV] VIX/VVIX/SKEW prevalece: VIX={vix_vvix_skew_data.get('vix_spot')} "
                         f"(p{vix_vvix_skew_data.get('vix_percentil')}) "
                         f"VVIX/VIX={vix_vvix_skew_data.get('ratio_vvix_vix')} "
                         f"SKEW={vix_vvix_skew_data.get('skew')} "
                         f"senal={vix_vvix_skew_data.get('señal_global','?').upper()}")
        except Exception as e:
            log.warning(f"  [CSV] VIX/VVIX/SKEW fallo (mantengo legacy): {e}")
            vix_vvix_skew_data = None

        # CSV-3: DIX + GEX (no tiene equivalente directo en legacy: bloque nuevo)
        try:
            dix_gex_data = leer_dix_gex_csv()
            if dix_gex_data:
                log.info(f"  [CSV] DIX/GEX nuevo bloque: DIX={dix_gex_data.get('dix')}% "
                         f"(p{dix_gex_data.get('dix_percentil')}, {dix_gex_data.get('dix_señal')}) | "
                         f"GEX={dix_gex_data.get('gex_b')}B "
                         f"(p{dix_gex_data.get('gex_percentil')}, {dix_gex_data.get('gex_señal')})")
        except Exception as e:
            log.warning(f"  [CSV] DIX/GEX fallo: {e}")
            dix_gex_data = None

        # CSV-4: Opciones QQQ (Barchart)
        try:
            qqq_opciones_csv = leer_qqq_opciones_csv()
            if qqq_opciones_csv:
                opciones_data = mapear_qqq_csv_al_legacy(qqq_opciones_csv, opciones_data)
                pcr_data      = mapear_pcr_csv_al_legacy(qqq_opciones_csv, pcr_data)
                log.info(f"  [CSV] QQQ opciones prevalece: venc={qqq_opciones_csv.get('vencimiento')} "
                         f"MaxPain={qqq_opciones_csv.get('max_pain')} "
                         f"({qqq_opciones_csv.get('dist_max_pain_pct'):+.1f}%) "
                         f"Resist={qqq_opciones_csv.get('resistencia_1')} "
                         f"Sop={qqq_opciones_csv.get('soporte_1')} "
                         f"PCR={qqq_opciones_csv.get('pcr')}")
        except Exception as e:
            log.warning(f"  [CSV] QQQ opciones fallo (mantengo legacy): {e}")
            qqq_opciones_csv = None
    else:
        log.info("\n[5.6/8] Capa CSV LOCAL DESACTIVADA (--nocsv) - usando solo APIs/Yahoo")

    # ═════════════════════════════════════════════════════════════════════════

    # ── 5.7 FASE 4: Market Regime Matching ───────────────────────────────────
    comparativa_correcciones = None
    log.info("\n[5.7/8] FASE 4 - Market Regime Matching (Crisis Fingerprint Engine)...")
    try:
        comparativa_correcciones = calcular_market_regime_matching(df, tecnicos_ndx, macro)
        if not comparativa_correcciones.get("error"):
            dom  = comparativa_correcciones.get("escenario_dominante", "?")
            rec  = comparativa_correcciones.get("recomendacion", "?")
            conf = comparativa_correcciones.get("confianza", 0)
            log.info(f"  OK MRM: Dominante={dom} | Conf={conf}%")
            log.info(f"     micro={comparativa_correcciones['micro_3pct']}% | "
                     f"tecnica={comparativa_correcciones['tecnica_7pct']}% | "
                     f"macro={comparativa_correcciones['macro_15pct']}% | "
                     f"bajista={comparativa_correcciones['bajista_25pct']}% | "
                     f"cisne={comparativa_correcciones['cisne_negro_30pct']}%")
            log.info(f"     Recomendacion: {rec}")
        else:
            log.warning(f"  [!] MRM error: {comparativa_correcciones.get('error')}")
    except Exception as e:
        log.error(f"  X Market Regime Matching fallo: {e}")
        comparativa_correcciones = {
            "micro_3pct": 0, "tecnica_7pct": 0, "macro_15pct": 0,
            "bajista_25pct": 0, "cisne_negro_30pct": 0,
            "escenario_dominante": "error", "recomendacion": "MONITOREAR SOPORTES",
            "confianza": 0, "detalle": str(e), "error": str(e),
            "fuente": "market_regime_matching_v4",
        }

    # ── 5.8 FASE 5: Amplitud, Estacionalidad y Kelly Sizing ──────────────────
    amplitud_data = None
    log.info("\n[5.8/8] FASE 5 - Amplitud de Mercado + Estacionalidad + Kelly Sizing...")
    try:
        amplitud_data = calcular_amplitud_mercado(df, tecnicos_ndx, vix_ts, precios)
        if not amplitud_data.get("error"):
            log.info(f"  OK Amplitud: Cobre/Oro={amplitud_data.get('ratio_cobre_oro')} ({amplitud_data.get('señal_cobre_oro')})")
            log.info(f"     ZScore_SMA200={amplitud_data.get('zscore_qqq_sma200')} ({amplitud_data.get('señal_zscore')})")
            log.info(f"     Estacional={amplitud_data.get('sesgo_estacional'):+d} | Factor={amplitud_data.get('factor_exposicion_recomendado'):.3f}")
            log.info(f"     Score Amplitud: {amplitud_data.get('score_amplitud'):+.1f}")
        else:
            log.warning(f"  [!] Amplitud: {amplitud_data.get('error')}")
    except Exception as e:
        log.error(f"  X Amplitud Fase 5 fallo: {e}")
        amplitud_data = {
            "ratio_cobre_oro": None, "tendencia_cobre_oro": "neutro",
            "señal_cobre_oro": "neutro", "zscore_qqq_sma200": None,
            "señal_zscore": "normal", "sesgo_estacional": 0,
            "descripcion_estacional": "Error en Fase 5",
            "factor_exposicion_recomendado": 1.0, "kelly_bruto": 0.5,
            "vix_scalar": 1.0, "score_amplitud": 0,
            "fuente": "fase5_amplitud_v5", "error": str(e),
        }

    # ── FASE 7: Proxy China ──────────────────────────────────────────────────
    log.info("\n[5.6/8] FASE 7 — Proxy Liquidez China (CNY + SOXX)...")
    proxy_china_data = None
    try:
        proxy_china_data = calcular_proxy_china(df)
        log.info("  China senal=" + str(proxy_china_data.get("senal")) + " score=" + str(proxy_china_data.get("score")))
    except Exception as e:
        log.warning("  [China] Fallo: " + str(e))
        proxy_china_data = {"senal": "neutro", "score": 0.0, "error": str(e)}

    # Inyectar proxy_china en macro para que calcular_scores lo use en SA
    if isinstance(macro, dict):
        macro["proxy_china"] = proxy_china_data
    elif macro is None:
        macro = {"proxy_china": proxy_china_data}

    # ── FASE 7: CTA Trigger Levels ───────────────────────────────────────────
    log.info("\n[5.65/8] FASE 7 — CTA Trigger Levels (Donchian 20/50)...")
    cta_data = None
    try:
        cta_data = calcular_cta_levels(df)
        log.info("  CTA senal=" + str(cta_data.get("senal_cta")) + " | D20: "
                 + str(cta_data.get("don20_low")) + "/" + str(cta_data.get("don20_high")))
    except Exception as e:
        log.warning("  [CTA] Fallo: " + str(e))
        cta_data = {"senal_cta": "neutro", "error": str(e)}

    # ── FASE 7: NDX100 Amplitud Real + SEC Insiders (modulos lentos) ────────
    ndx100_breadth_data = None
    sec_insiders_data   = None

    if not args.noinstitucional:
        log.info("\n[5.67/8] FASE 7 — Amplitud NDX-100 Real (puede tardar 60-120s)...")
        try:
            ndx100_breadth_data = calcular_amplitud_ndx100(df)
            if ndx100_breadth_data.get("net_breadth_pct") is not None:
                log.info("  NDX100 breadth=" + str(ndx100_breadth_data.get("net_breadth_pct"))
                         + "% senal=" + str(ndx100_breadth_data.get("senal")))
        except Exception as e:
            log.warning("  [NDX100] Fallo: " + str(e))
            ndx100_breadth_data = {"senal": "neutro", "score": 0.0, "error": str(e)}

        log.info("\n[5.68/8] FASE 7 — SEC Form 4 Insiders...")
        try:
            sec_insiders_data = calcular_sec_insiders()
            log.info("  SEC senal=" + str(sec_insiders_data.get("senal")))
        except Exception as e:
            log.warning("  [SEC] Fallo: " + str(e))
            sec_insiders_data = {"senal": "neutro", "error": str(e)}
    else:
        log.info("\n[5.67/8] Modulos institucionales saltados (--noinstitucional)")
        ndx100_breadth_data = {"senal": "neutro", "score": 0.0, "error": "saltado_noinstitucional"}
        sec_insiders_data   = {"senal": "neutro", "error": "saltado_noinstitucional"}

    # Inyectar ndx100_breadth en amplitud_data para score_amplitud_fn
    if isinstance(amplitud_data, dict):
        amplitud_data["ndx100_breadth"] = ndx100_breadth_data

    # ── 6. Scores multi-horizonte ──────────────────────────────────────────────
    log.info("\n[6/8] Calculando scores multi-horizonte...")
    scores = calcular_scores(
        tecnicos_ndx, tecnicos_qqq, vix_ts, giro, flows, precios,
        macro=macro, cot=cot_data, opciones=opciones_data, pcr=pcr_data,
        amplitud=amplitud_data
    )
    hs = scores["horizontes"]
    for k, v in hs.items():
        sc = v["score"]
        est = v["estado"].upper()
        log.info(f"  {k}: {sc:+.1f} ({est}, conf {v['conf']}%)")

    # ── 7. Construir y exportar JSON ───────────────────────────────────────────
    log.info("\n[7/8] Exportando datos_radar.json...")

    if macro is None:
        macro = {
            "error": "fred_no_disponible",
            "curva": {"t3m": None, "t10y": round(precios["tnx"] / 10, 3) if precios.get("tnx") else None},
            "score": scores["componentes"]["macro"],
            "desc":  "FRED no disponible — usando score macro aproximado",
        }

    datos_json = {
        "version":      VERSION,
        "ts":           datetime.now().isoformat(),
        "precio":       precios,
        "tecnicos":     tecnicos_ndx,
        "tecnicosQQQ":  tecnicos_qqq,
        "vixTS":        vix_ts,
        # ── vixTermStructure: alias con vx1/vx2 que espera el frontend Táctico 2-5D ──
        # El frontend aplicarDatosRadar() busca data.vixTermStructure.{spot, vx1, vx2}
        # vixTS (de parsear_vix_ts_txt) tiene front_month/second_month → los mapeamos aquí
        "vixTermStructure": {
            "spot":          vix_ts.get("spot"),
            "vx1":           (vix_ts.get("front_month") or {}).get("precio"),
            "vx2":           (vix_ts.get("second_month") or {}).get("precio"),
            "vx1_symbol":    (vix_ts.get("front_month") or {}).get("symbol"),
            "vx2_symbol":    (vix_ts.get("second_month") or {}).get("symbol"),
            "vx1_expiry":    (vix_ts.get("front_month") or {}).get("expiry"),
            "vx2_expiry":    (vix_ts.get("second_month") or {}).get("expiry"),
            "spread1":       vix_ts.get("spread1"),
            "spread1Pct":    vix_ts.get("spread1Pct"),
            "backwardation": vix_ts.get("backwardation"),
            "slope_1m2m":    vix_ts.get("slope_1m2m"),
            "señal":         vix_ts.get("señal"),
            "desc":          vix_ts.get("desc"),
            "fuente":        vix_ts.get("fuente", "historico"),
            "usando_settlement": vix_ts.get("usando_settlement", False),
        },
        "giro":         giro,
        "flows":        flows,
        "liquidez":     liquidez,
        "macro":        macro,
        "scores":       scores,
        # Fase 3 — datos reales
        "cot":          cot_data or {
            "error": "no_ejecutado", "señal": "neutro",
            "largos": None, "cortos": None, "neto": None,
            "pctLargo": None, "cambioNeto": None, "trend4w": None,
            "señalDealers": "neutro", "netoDealers": None, "desc": "",
        },
        "opciones":     opciones_data or {
            "error": "no_ejecutado",
            "gex": {"estado": "neutro", "valor": 0, "trampa": False, "desc": ""},
        },
        "pcr":          pcr_data or {
            "error": "no_ejecutado",
            "equity": None, "total": None,
            "señal": "neutro", "desc": "",
        },
        # Fase 4 — Market Regime Matching (Crisis Fingerprint Engine)
        "comparativa_correcciones": comparativa_correcciones or {
            "micro_3pct":        0,
            "tecnica_7pct":      0,
            "macro_15pct":       0,
            "bajista_25pct":     0,
            "cisne_negro_30pct": 0,
            "escenario_dominante": "indeterminado",
            "recomendacion":     "MONITOREAR SOPORTES",
            "confianza":         0,
            "detalle":           "MRM no ejecutado",
            "fuente":            "market_regime_matching_v4",
        },
        # Fase 5 — Amplitud de Mercado, Estacionalidad y Kelly Sizing
        "amplitud_mercado": amplitud_data or {
            "ratio_cobre_oro":               None,
            "tendencia_cobre_oro":           "neutro",
            "señal_cobre_oro":               "neutro",
            "zscore_qqq_sma200":             None,
            "señal_zscore":                  "normal",
            "sesgo_estacional":              0,
            "descripcion_estacional":        "Fase 5 no ejecutada",
            "factor_exposicion_recomendado": 1.0,
            "kelly_bruto":                   0.5,
            "vix_scalar":                    1.0,
            "score_amplitud":                0,
            "fuente":                        "fase5_amplitud_v5",
            "error":                         "no_ejecutado",
        },
        # Fase 7 — nuevos modulos
        "cta_levels":    cta_data or {"senal_cta": "neutro", "error": "no_ejecutado"},
        "sec_insiders":  sec_insiders_data or {"senal": "neutro", "error": "no_ejecutado"},
        # ──────────────────────────────────────────────────────────────────────
        # BLOQUE CSV LOCAL (v8.0 unificado) — datos enriquecidos del CSV
        # ──────────────────────────────────────────────────────────────────────
        # Estos bloques contienen el output COMPLETO del CSV local, incluyendo
        # campos que NO existen en los bloques legacy (percentiles 1044sem,
        # umbrales calibrados, historicos 52s/90d, ratio VVIX/VIX, SKEW, DIX,
        # GEX en B$, etc.). El frontend puede leerlos para nuevos paneles.
        # Si la capa CSV esta desactivada (--nocsv) o un CSV no existe,
        # el campo correspondiente sera null.
        "csv_cot":           cot_csv_data,           # COT NASDAQ MINI completo con percentiles
        "csv_vix_vvix_skew": vix_vvix_skew_data,     # VIX+VVIX+SKEW + ratio + term structure proxy
        "csv_dix_gex":       dix_gex_data,           # DIX% + GEX B$ SqueezeMetrics
        "csv_qqq_opciones":  qqq_opciones_csv,       # Max Pain + muros OI + PCR Barchart
        "csv_activo":        (not args.nocsv),
        # ──────────────────────────────────────────────────────────────────────
        "fase_activa": 8,
        "proximas_fases": "Fase9=HMM_clustering_regimenes+SEC_13F_completo",
    }

    # ── INYECCIÓN gex_manual.json → maxpain + derivados (auto-rellena Radar 2-5D) ──
    inyectar_gex_manual(datos_json)

    exportar_json(datos_json)

    # ── 8. Git push ────────────────────────────────────────────────────────────
    if not args.nogit:
        log.info("\n[8/8] Subiendo datos_radar.json a GitHub...")
        exito = git_push()
        if not exito:
            log.warning("  ⚠️  Git push falló. JSON guardado localmente.")
    else:
        log.info("\n[8/8] Git saltado (--nogit activo)")

    log.info("\n" + "=" * 65)
    log.info(f"OK RADAR v{VERSION} ACTUALIZADO CORRECTAMENTE")
    log.info(f"   JSON: {JSON_PATH}")
    log.info(f"   NDX:  {precios.get('ndx')} | VIX: {precios.get('vix')}")
    log.info(f"   Score Macro FRED: {macro.get('score', '?'):+}")
    log.info(f"   Score 2D: {hs['d2']['score']:+.1f} ({hs['d2']['estado'].upper()})")
    log.info(f"   Score 1S: {hs['w1']['score']:+.1f} ({hs['w1']['estado'].upper()})")
    log.info(f"   Score 4S: {hs['w4']['score']:+.1f} ({hs['w4']['estado'].upper()})")

    # ── Resumen capa CSV (v8.0) ──────────────────────────────────────────────
    if not args.nocsv:
        csv_status = []
        if cot_csv_data:       csv_status.append(f"COT(p{cot_csv_data.get('percentil_historico')},{cot_csv_data.get('semanas_historico')}sem)")
        if vix_vvix_skew_data: csv_status.append(f"VIX(p{vix_vvix_skew_data.get('vix_percentil')},ratio={vix_vvix_skew_data.get('ratio_vvix_vix')})")
        if dix_gex_data:       csv_status.append(f"DIX({dix_gex_data.get('dix')}%,{dix_gex_data.get('dix_señal')})")
        if qqq_opciones_csv:   csv_status.append(f"MaxPain={qqq_opciones_csv.get('max_pain')}")
        if csv_status:
            log.info(f"   CSV LOCAL: {' | '.join(csv_status)}")
        else:
            log.info(f"   CSV LOCAL: sin datos (carpeta {DATA_CSV_DIR} vacia o ausente)")

    # Alertas Fase 3
    if cot_data and not cot_data.get("error"):
        log.info(f"   COT: {cot_data.get('pctLargo')}% largos | {cot_data.get('señal').upper()} | Dealers={cot_data.get('señalDealers')}")
    if opciones_data and not opciones_data.get("error"):
        v1 = opciones_data.get("v1") or {}
        log.info(f"   MaxPain: {v1.get('maxPain')} | GEX={opciones_data['gex']['estado']}")
    if pcr_data and not pcr_data.get("error"):
        log.info(f"   PCR CBOE: {pcr_data.get('total')} ({pcr_data.get('señal').upper()})")

    # Alertas Fase 4
    if comparativa_correcciones and not comparativa_correcciones.get("error"):
        dom  = comparativa_correcciones.get("escenario_dominante", "?")
        rec  = comparativa_correcciones.get("recomendacion", "?")
        conf = comparativa_correcciones.get("confianza", 0)
        cisne = comparativa_correcciones.get("cisne_negro_30pct", 0)
        baj   = comparativa_correcciones.get("bajista_25pct", 0)
        log.info(f"   MRM: Dominante={dom} ({conf}% conf)")
        log.info(f"   RECOMENDACION: {rec}")
        if cisne > 50 or baj > 60:
            log.warning(f"   ALERTA MRM: Cisne={cisne}% / Bajista={baj}% — PRECAUCION MAXIMA")

    macro_tipos = macro.get("tiposRealesOro", {}) if isinstance(macro, dict) else {}
    if macro_tipos.get("alerta"):
        log.warning(f"   DRENAJE LIQUIDEZ - {macro_tipos.get('desc', '')}")

    # Alertas Fase 5
    if amplitud_data and not amplitud_data.get("error"):
        sa_score = amplitud_data.get("score_amplitud", 0)
        fe       = amplitud_data.get("factor_exposicion_recomendado", 1.0)
        zscore   = amplitud_data.get("zscore_qqq_sma200")
        señal_cu = amplitud_data.get("señal_cobre_oro", "neutro")
        log.info(f"   AMPLITUD: Score={sa_score:+.1f} | Cobre/Oro={señal_cu} | ZScore={zscore}")
        log.info(f"   KELLY SIZING: Factor exposicion recomendado = {fe:.3f}x")
        if fe < 0.5:
            log.warning(f"   ALERTA KELLY: Factor bajo ({fe:.3f}x) — mercado sugiere reducir exposicion")
        if amplitud_data.get("señal_zscore") == "sobreextendido":
            log.warning(f"   ALERTA ZSCORE: QQQ sobreextendido vs SMA200 (Z={zscore}) — agotamiento tecnico")


    # ── ALERTAS EMAIL FASE 6 ─────────────────────────────────────────────────
    FUENTES_EMAIL = {
        "COT":      "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
        "Opciones": "https://finance.yahoo.com/quote/QQQ/options",
        "FRED":     "https://fred.stlouisfed.org",
        "PCR":      "https://www.cboe.com/data/volatility-and-put-call-ratio-data/",
        "Amplitud": "",
    }
    if cot_data and cot_data.get("error") and cot_data.get("error") not in ("saltado_noderivativos",):
        enviar_alerta_email("COT", str(cot_data.get("error")), FUENTES_EMAIL["COT"])
    if opciones_data and opciones_data.get("error") and opciones_data.get("error") not in ("saltado_noderivativos",):
        enviar_alerta_email("Opciones", str(opciones_data.get("error")), FUENTES_EMAIL["Opciones"])
    if macro and isinstance(macro, dict) and macro.get("error") and macro.get("error") not in ("fred_no_disponible",):
        enviar_alerta_email("FRED", str(macro.get("error")), FUENTES_EMAIL["FRED"])
    if pcr_data and pcr_data.get("error") and pcr_data.get("error") not in ("saltado_noderivativos",):
        enviar_alerta_email("PCR", str(pcr_data.get("error")), FUENTES_EMAIL["PCR"])
    if amplitud_data and amplitud_data.get("error") and amplitud_data.get("error") not in ("no_ejecutado",):
        enviar_alerta_email("Amplitud", str(amplitud_data.get("error")), FUENTES_EMAIL["Amplitud"])
    # ─────────────────────────────────────────────────────────────────────────

    # ── ALERTAS EMAIL FASE 7 — NIVEL 2 ───────────────────────────────────────
    vix_actual    = precios.get("vix") or 0
    rsi_actual    = ((tecnicos_ndx or {}).get("d") or {}).get("rsi14") or 50
    cisne_pct     = (comparativa_correcciones or {}).get("cisne_negro_30pct") or 0
    kelly_factor  = (amplitud_data or {}).get("factor_exposicion_recomendado") or 1.0
    dealers_senal = (cot_data or {}).get("señalDealers") or "neutro"
    breadth_senal = ((amplitud_data or {}).get("ndx100_breadth") or {}).get("senal") or "neutro"

    try:
        if float(vix_actual) > 30:
            enviar_alerta_email(
                "VIX EXTREMO",
                "VIX=" + str(vix_actual) + " supera umbral critico 30",
                "https://www.cboe.com/tradable_products/vix/"
            )
    except Exception:
        pass
    try:
        if float(cisne_pct) > 60:
            enviar_alerta_email(
                "CISNE NEGRO DETECTADO",
                "MRM cisne_negro=" + str(cisne_pct) + "pct - similitud critica con colapsos historicos",
                ""
            )
    except Exception:
        pass
    try:
        if float(kelly_factor) < 0.3:
            enviar_alerta_email(
                "KELLY BAJO - REDUCIR EXPOSICION",
                "Factor Kelly=" + str(round(float(kelly_factor), 3)) + " por debajo de umbral 0.30",
                ""
            )
    except Exception:
        pass
    try:
        if dealers_senal == "distribucion" and float(rsi_actual) > 70:
            enviar_alerta_email(
                "DISTRIBUCION INSTITUCIONAL",
                "Dealers distribuyendo con RSI=" + str(round(float(rsi_actual), 1)) + " - posible techo",
                "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
            )
    except Exception:
        pass
    try:
        if breadth_senal == "bajista_fuerte":
            enviar_alerta_email(
                "AMPLITUD NDX100 MUY DEBIL",
                "Net New Highs/Lows negativo extremo - divergencia bajista en amplitud",
                ""
            )
    except Exception:
        pass
    # ─────────────────────────────────────────────────────────────────────────
    log.info("=" * 65)


if __name__ == "__main__":
    main()
