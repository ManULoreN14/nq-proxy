"""
motor_manengis.py  v2.4
========================
Motor principal NQ Unified.
Genera manengis_tactico.json con datos reales del dia.

Cambios v2.4:
- FRED: usa API JSON oficial con FRED_API_KEY (env var o hardcoded fallback)
- CFTC: cambia a descarga ZIP historico semanal (no OData)
- Similitud: fix timezone robusto

Ejecutado por GitHub Actions L-V 20:15 UTC (22:15 Madrid)
Dependencias: pip install yfinance requests pandas numpy
"""

import json, datetime, sys, warnings, os, io, zipfile
import numpy as np
from pathlib import Path
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    import requests
    import pandas as pd
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable,"-m","pip","install",
                           "yfinance","requests","pandas","numpy","-q"])
    import yfinance as yf, requests, pandas as pd

SCRIPT_DIR  = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "manengis_tactico.json"
MAG7 = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA"]

# FRED API KEY - se lee de variable de entorno (GitHub Actions secret)
# o del archivo .env local si existe
FRED_API_KEY = os.environ.get("FRED_API_KEY", "f15ed9ee86d337183138a81bfd4952cb")

def utcnow_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

# ── HELPERS PRECIOS ──────────────────────────────────────────────────────────

def get_hist(sym, period="60d"):
    try:
        h = yf.Ticker(sym).history(period=period)
        return h["Close"] if not h.empty else None
    except Exception as e:
        print(f"  ! {sym}: {e}")
        return None

def last_val(s):
    if s is None or s.empty: return None
    v = s.iloc[-1]
    return None if (isinstance(v,float) and np.isnan(v)) else round(float(v),4)

def calc_ema(s, n):
    if s is None or len(s)<n: return None
    v = s.ewm(span=n,adjust=False).mean().iloc[-1]
    return round(float(v),2) if not np.isnan(v) else None

def calc_rsi(s, n=14):
    """
    RSI Wilder con EWM (no SMA).
    Sprint 4 E.1: ANTES motor usaba rolling().mean() (SMA), pero actualizar_radar.py
    usa ewm(com=n-1, adjust=False).mean() (Wilder). Para el mismo activo daban
    valores distintos. Ahora ambos scripts calculan RSI igual.
    """
    if s is None or len(s)<n+2: return None
    d = s.diff().dropna()
    g = d.clip(lower=0).ewm(com=n-1, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(com=n-1, adjust=False).mean()
    rs = g/l.replace(0,np.nan)
    r  = 100-(100/(1+rs))
    v  = r.dropna().iloc[-1]
    return round(float(v),2) if not np.isnan(v) else None

def calc_atr(sym, n=14, period="60d"):
    try:
        h = yf.Ticker(sym).history(period=period)
        if h.empty or len(h)<n: return None
        hi=h["High"]; lo=h["Low"]; cl=h["Close"]
        tr = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
        v  = tr.rolling(n).mean().iloc[-1]
        return round(float(v),2) if not np.isnan(v) else None
    except: return None

# ── FRED (API JSON oficial con clave) ────────────────────────────────────────

def fred_series(sid):
    """API JSON de FRED con clave gratuita. Fiable desde cualquier servidor."""
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={sid}&api_key={FRED_API_KEY}"
        f"&file_type=json&sort_order=desc&limit=2"
    )
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
        obs = r.json().get("observations", [])
        validos = [o for o in obs if o.get("value",".") != "."]
        if not validos: return None, None
        curr = round(float(validos[0]["value"]), 4)
        prev = round(float(validos[1]["value"]), 4) if len(validos)>1 else curr
        return curr, prev
    except Exception as e:
        print(f"  ! FRED {sid}: {e}")
        return None, None

# ── COT (CFTC ZIP semanal) ───────────────────────────────────────────────────

def _cot_from_zip():
    """
    Descarga el ZIP COT del anio actual desde CFTC y devuelve DataFrame normalizado.
    Normaliza nombres de columnas: guiones -> guiones_bajos, espacios -> guiones_bajos.
    """
    year = datetime.date.today().year
    url  = f"https://www.cftc.gov/files/dea/history/fut_fin_xls_{year}.zip"
    try:
        r = requests.get(url, timeout=30,
                         headers={"User-Agent":
                                  "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        z = zipfile.ZipFile(io.BytesIO(r.content))
        nombre = z.namelist()[0]
        with z.open(nombre) as f:
            raw = f.read()
        # Intentar leer como XLS/XLSX binario, fallback a CSV latin-1
        try:
            df = pd.read_excel(io.BytesIO(raw), engine="xlrd")
        except Exception:
            try:
                df = pd.read_excel(io.BytesIO(raw), engine="openpyxl")
            except Exception:
                df = pd.read_csv(io.BytesIO(raw), encoding="latin-1", low_memory=False)
        # Normalizar nombres de columnas: espacios y guiones -> guiones_bajos
        df.columns = [c.strip().replace(" ","_").replace("-","_") for c in df.columns]
        # Log de columnas clave para diagnóstico (Leveraged, Dealer, Asset)
        cols_inst = [c for c in df.columns if any(k in c for k in
                     ("Leveraged","Lev_Money","Dealer","Asset_Mgr","Asset_Manager"))]
        print(f"  CFTC ZIP OK: {len(df)} filas")
        print(f"  CFTC cols institucionales: {cols_inst[:10]}")
        return df
    except Exception as e:
        print(f"  ! CFTC ZIP: {e}")
        return None

def _find_col(df, *keywords):
    """Encuentra la primera columna que contenga TODAS las palabras clave."""
    for c in df.columns:
        if all(k.lower() in c.lower() for k in keywords):
            return c
    return None

def cot_nq():
    """
    COT NQ Futures desde ZIP financiero CFTC (fut_fin_xls).
    El ZIP 'Traders in Financial Futures' usa estas columnas reales:
      - Leveraged_Funds_Positions_Long_All  / _Short_All  (especuladores)
      - Asset_Mgr_Positions_Long_All        / _Short_All  (gestoras)
      - Dealer_Positions_Long_All           / _Short_All  (dealers/smart money)
    Fecha: Report_Date_as_MM_DD_YYYY
    """
    df = _cot_from_zip()
    if df is None:
        return {"error": "No disponible"}

    col_market = "Market_and_Exchange_Names"
    col_fecha  = "Report_Date_as_MM_DD_YYYY"

    # ── Leveraged Funds (Large Speculators: hedge funds, CTAs) ───────────────
    # Nombres reales en el ZIP financiero CFTC 2024-2026:
    col_lev_l = None
    col_lev_s = None
    for candidate in [
        "Leveraged_Funds_Positions_Long_All",   # nombre real confirmado
        "Lev_Money_Positions_Long_All",          # nombre alternativo antiguo
    ]:
        if candidate in df.columns:
            col_lev_l = candidate
            break
    for candidate in [
        "Leveraged_Funds_Positions_Short_All",
        "Lev_Money_Positions_Short_All",
    ]:
        if candidate in df.columns:
            col_lev_s = candidate
            break
    # Fallback genérico si los nombres exactos no aparecen
    if not col_lev_l:
        col_lev_l = _find_col(df, "Leveraged", "Long") or _find_col(df, "Lev", "Long")
    if not col_lev_s:
        col_lev_s = _find_col(df, "Leveraged", "Short") or _find_col(df, "Lev", "Short")

    # ── Asset Manager / Institutional ────────────────────────────────────────
    col_am_l = None
    col_am_s = None
    for candidate in ["Asset_Mgr_Positions_Long_All", "Asset_Manager_Positions_Long_All"]:
        if candidate in df.columns:
            col_am_l = candidate
            break
    for candidate in ["Asset_Mgr_Positions_Short_All", "Asset_Manager_Positions_Short_All"]:
        if candidate in df.columns:
            col_am_s = candidate
            break
    if not col_am_l:
        col_am_l = _find_col(df, "Asset", "Long")
    if not col_am_s:
        col_am_s = _find_col(df, "Asset", "Short")

    # ── Dealer / Intermediary (Smart Money) ──────────────────────────────────
    col_dl_l = None
    col_dl_s = None
    for candidate in ["Dealer_Positions_Long_All", "Dealer_Intermediary_Positions_Long_All"]:
        if candidate in df.columns:
            col_dl_l = candidate
            break
    for candidate in ["Dealer_Positions_Short_All", "Dealer_Intermediary_Positions_Short_All"]:
        if candidate in df.columns:
            col_dl_s = candidate
            break
    if not col_dl_l:
        col_dl_l = _find_col(df, "Dealer", "Long")
    if not col_dl_s:
        col_dl_s = _find_col(df, "Dealer", "Short")

    # ── Diagnóstico en log para debugging futuro ──────────────────────────────
    print(f"  cot_nq cols → lev_l={col_lev_l} | lev_s={col_lev_s}")
    print(f"               am_l={col_am_l}  | am_s={col_am_s}")
    print(f"               dl_l={col_dl_l}  | dl_s={col_dl_s}")
    if not col_lev_l or not col_lev_s:
        # Volcar todas las columnas para diagnóstico
        print(f"  cot_nq TODAS LAS COLS: {list(df.columns)}")

    if not col_lev_l or not col_lev_s or col_market not in df.columns:
        return {"error": f"Columnas Leveraged Funds no encontradas. Cols disponibles: {list(df.columns)[:12]}"}

    mask = df[col_market].astype(str).str.contains("NASDAQ MINI", na=False, case=False)
    sub  = df[mask].copy()
    if sub.empty:
        return {"error": "NQ no encontrado en ZIP"}

    sub["_fecha"] = pd.to_datetime(sub[col_fecha], errors="coerce", dayfirst=False)
    sub = sub.sort_values("_fecha", ascending=False).reset_index(drop=True)
    c = sub.iloc[0]; p = sub.iloc[1] if len(sub)>1 else sub.iloc[0]

    ll   = int(c.get(col_lev_l, 0) or 0)
    ls   = int(c.get(col_lev_s, 0) or 0)
    al   = int(c.get(col_am_l,  0) or 0) if col_am_l else 0
    as_  = int(c.get(col_am_s,  0) or 0) if col_am_s else 0
    dl   = int(c.get(col_dl_l,  0) or 0) if col_dl_l else 0
    ds   = int(c.get(col_dl_s,  0) or 0) if col_dl_s else 0
    ll_p = int(p.get(col_lev_l, 0) or 0)
    ls_p = int(p.get(col_lev_s, 0) or 0)

    neto      = ll - ls
    neto_prev = ll_p - ls_p
    pct  = round(ll/(ll+ls)*100,1) if (ll+ls)>0 else 50
    # Sesgo contrario: <35% largos = specs muy cortos = señal ALCISTA contraria
    #                  >65% largos = specs muy largos = señal BAJISTA contraria
    sesgo = "bajista" if pct>65 else "alcista" if pct<35 else "neutro"

    print(f"  cot_nq resultado: lev_long={ll:,} lev_short={ls:,} neto={neto:,} pct={pct}% sesgo={sesgo}")

    return {
        "fecha_reporte":      str(c.get(col_fecha, ""))[:10],
        "leveraged_long":     ll,
        "leveraged_short":    ls,
        "leveraged_net":      neto,
        "leveraged_net_prev": neto_prev,
        "asset_manager_long": al,  "asset_manager_short": as_,
        "asset_manager_net":  al - as_,
        "dealer_long":        dl,  "dealer_short": ds,
        "dealer_net":         dl - ds,
        "pct_largo": pct, "sesgo": sesgo,
        "descripcion": (
            f"Leveraged Funds {'corto' if neto<0 else 'largo'} "
            f"neto {abs(neto):,} contratos en NQ. Sesgo: {sesgo.upper()}. "
            f"({pct}% largos · Dealers neto {dl-ds:+,})"
        )
    }

def cot_vix():
    """
    COT VIX Futures (codigo 1170E1) desde ZIP financiero CFTC.
    Usa Lev_Money_* como proxy de especuladores en VIX.
    Logica INVERSA al NQ: cortos en VIX = alcista para el mercado.
    """
    df = _cot_from_zip()
    if df is None:
        return {"error": "No disponible"}

    col_market = "Market_and_Exchange_Names"
    col_codigo = "CFTC_Contract_Market_Code"
    col_fecha  = "Report_Date_as_MM_DD_YYYY"

    # Nombres reales del ZIP financiero CFTC (mismo fix que cot_nq)
    col_lev_l = None
    col_lev_s = None
    for candidate in ["Leveraged_Funds_Positions_Long_All", "Lev_Money_Positions_Long_All"]:
        if candidate in df.columns:
            col_lev_l = candidate
            break
    for candidate in ["Leveraged_Funds_Positions_Short_All", "Lev_Money_Positions_Short_All"]:
        if candidate in df.columns:
            col_lev_s = candidate
            break
    if not col_lev_l:
        col_lev_l = _find_col(df, "Leveraged", "Long") or _find_col(df, "Lev", "Long")
    if not col_lev_s:
        col_lev_s = _find_col(df, "Leveraged", "Short") or _find_col(df, "Lev", "Short")

    print(f"  cot_vix cols → lev_l={col_lev_l} | lev_s={col_lev_s}")

    if not col_lev_l or not col_lev_s:
        return {"error": f"Columnas VIX no encontradas. Cols: {list(df.columns)[:12]}"}

    # Estrategia de filtrado en cascada:
    # 1) Codigo de contrato 1170E1 (lo mas fiable)
    # 2) Nombre con VIX + CBOE
    # 3) Solo VIX en el nombre
    sub = pd.DataFrame()
    if col_codigo in df.columns:
        m = df[col_codigo].astype(str).str.strip() == "1170E1"
        if m.any():
            sub = df[m].copy()
            print(f"  cot_vix: encontrado por codigo 1170E1 ({len(sub)} filas)")

    if sub.empty:
        m = (df[col_market].astype(str).str.contains("VIX", na=False, case=False) &
             df[col_market].astype(str).str.contains("CBOE", na=False, case=False))
        if m.any():
            sub = df[m].copy()
            print(f"  cot_vix: encontrado por VIX+CBOE ({len(sub)} filas)")

    if sub.empty:
        m = df[col_market].astype(str).str.contains("VIX", na=False, case=False)
        if m.any():
            sub = df[m].copy()
            print(f"  cot_vix: encontrado por VIX ({len(sub)} filas)")

    if sub.empty:
        # Diagnostico: mostrar nombres unicos disponibles
        nombres_unicos = df[col_market].astype(str).unique()[:20] if col_market in df.columns else []
        print(f"  cot_vix: nombres en el archivo: {list(nombres_unicos)}")
        return {"error": "VIX no encontrado en ZIP"}

    sub["_fecha"] = pd.to_datetime(sub[col_fecha], errors="coerce", dayfirst=False)
    sub = sub.sort_values("_fecha", ascending=False).reset_index(drop=True)
    c = sub.iloc[0]; p = sub.iloc[1] if len(sub)>1 else sub.iloc[0]

    nl   = int(c.get(col_lev_l, 0) or 0)
    ns   = int(c.get(col_lev_s, 0) or 0)
    nl_p = int(p.get(col_lev_l, 0) or 0)
    ns_p = int(p.get(col_lev_s, 0) or 0)

    neto      = nl - ns
    neto_prev = nl_p - ns_p
    pct  = round(nl/(nl+ns)*100,1) if (nl+ns)>0 else 50
    if neto < -20000 or pct < 48:
        senal = "alcista"
    elif neto > 20000 or pct > 52:
        senal = "bajista"
    else:
        senal = "neutro"

    return {
        "fecha_reporte": str(c.get(col_fecha, ""))[:10],
        "nc_long": nl, "nc_short": ns,
        "neto": neto, "neto_prev": neto_prev,
        "pct_largo": pct, "senal": senal,
        "descripcion": (
            f"Leveraged Money {'cortos' if neto<0 else 'largos'} "
            f"netos en VIX: {abs(neto):,} contratos. Senal: {senal.upper()}."
        )
    }

# ── PCR CBOE ─────────────────────────────────────────────────────────────────

def pcr_cboe():
    """
    Descarga el CSV diario de volumen de opciones del CBOE y extrae
    TOTAL PUT/CALL RATIO y EQUITY PUT/CALL RATIO.
    URL: https://cdn.cboe.com/api/global/us_indices/daily_prices/OPTIONS_VOLUME_REPORT.csv
    Devuelve dict con claves: total, equity, fecha, descripcion.

    Sprint 8: PRIORIDAD 0 — leer PCR.txt (generado por preparar_datos.py a
    partir de la descarga manual del usuario) antes de intentar pegarle
    directo a la URL de CBOE, que en producción (IP de GitHub Actions)
    devuelve 403 Forbidden siempre. Mismo patrón que ya usa
    actualizar_radar.py en parsear_pcr_txt().
    """
    pcr_txt_local = SCRIPT_DIR / "PCR.txt"
    if pcr_txt_local.exists():
        try:
            valores = {}
            for ln in pcr_txt_local.read_text(encoding="utf-8", errors="replace").splitlines():
                partes = ln.split("\t")
                if len(partes) < 2:
                    continue
                etiqueta, valor = partes[0].strip().upper(), partes[-1].strip()
                try:
                    v = float(valor)
                except ValueError:
                    continue
                if etiqueta.startswith("TOTAL"):
                    valores["total"] = v
                elif etiqueta.startswith("EQUITY"):
                    valores["equity"] = v
                elif etiqueta.startswith("INDEX"):
                    valores["index"] = v
                elif etiqueta.startswith("SPX"):
                    valores["spx"] = v
            if "total" in valores or "equity" in valores:
                valores["fecha"] = pcr_txt_local.read_text(encoding="utf-8", errors="replace").splitlines()[0].strip()
                valores["fuente"] = "PCR.txt"
                return valores
        except Exception as e:
            print(f"  ! PCR.txt no se pudo leer, probando CBOE directo: {e}")

    import io
    URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/OPTIONS_VOLUME_REPORT.csv"
    try:
        resp = requests.get(URL, timeout=15,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        # Normalizar nombres de columnas: quitar espacios y pasar a minúsculas
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        # Columnas esperadas: 'date', 'total_put_call_ratio', 'equity_put_call_ratio'
        # También pueden aparecer como 'p/c_ratio_total', 'p/c_ratio_equity', etc.
        # Buscamos de forma flexible
        def _find_col(df, *candidates):
            for c in candidates:
                if c in df.columns:
                    return c
            # búsqueda parcial
            for c in df.columns:
                for cand in candidates:
                    if cand.replace("_", "") in c.replace("_", "").replace("/", ""):
                        return c
            return None

        col_total  = _find_col(df, "total_put_call_ratio", "p/c_ratio_total",
                                "total_put/call_ratio", "totalputcallratio")
        col_equity = _find_col(df, "equity_put_call_ratio", "p/c_ratio_equity",
                                "equity_put/call_ratio", "equityputcallratio")
        col_date   = _find_col(df, "date", "trade_date", "fecha")

        # Usar la última fila con datos válidos
        df_valid = df.dropna(subset=[c for c in [col_total, col_equity] if c])
        if df_valid.empty:
            return {"error": "CSV CBOE sin filas válidas"}


        row   = df_valid.iloc[-1]
        fecha = str(row[col_date])[:10] if col_date else "desconocida"
        total  = round(float(row[col_total]),  3) if col_total  else None
        equity = round(float(row[col_equity]), 3) if col_equity else None

        return {
            "total":  total,
            "equity": equity,
            "index":  None,   # no disponible en este CSV
            "spx":    None,   # no disponible en este CSV
            "fecha":  fecha,
            "descripcion": (
                f"PCR Total={total} Equity={equity} · Fecha {fecha}. "
                f"{'Equity<0.6 = euforia' if equity and equity<0.6 else 'Equity>1.0 = miedo' if equity and equity>1.0 else 'Zona normal'}."
            )
        }
    except Exception as e:
        return {"error": f"pcr_cboe: {e}"}


# ── FEAR & GREED ─────────────────────────────────────────────────────────────

def fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1&format=json",
                         timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        d = r.json()
        score  = float(d["data"][0]["value"])
        rating = d["data"][0]["value_classification"]
        estado = ("miedo_extremo" if score<20 else "miedo" if score<40 else
                  "neutro" if score<60 else "codicia" if score<80 else "euforia_extrema")
        return {"score":score,"estado":estado,"rating":rating,"fuente":"alternative.me"}
    except Exception as e:
        print(f"  ! Fear&Greed: {e}")
    return {"score":None,"estado":"sin_datos","rating":None,"fuente":"sin_datos"}

# ── BREADTH MAG7 ─────────────────────────────────────────────────────────────

def calcular_breadth(tickers, period="60d"):
    detalle = []
    for sym in tickers:
        try:
            s = get_hist(sym, period)
            if s is None or len(s)<50: continue
            precio=last_val(s); e20=calc_ema(s,20); e50=calc_ema(s,50)
            detalle.append({
                "ticker":sym,"precio":precio,"ema20":e20,"ema50":e50,
                "sobre_ema20":bool(precio>e20) if e20 else False,
                "sobre_ema50":bool(precio>e50) if e50 else False,
            })
        except: pass
    n=len(detalle)
    s20=sum(1 for r in detalle if r["sobre_ema20"])
    s50=sum(1 for r in detalle if r["sobre_ema50"])
    pct20=round(s20/n*100,1) if n else 0
    pct50=round(s50/n*100,1) if n else 0
    return {"tickers_validos":n,"sobre_ema20":s20,"sobre_ema50":s50,
            "pct_sobre_ema20":pct20,"pct_sobre_ema50":pct50,
            "detalle":detalle,"divergencia":pct50<60}

# ── SIMILITUD HISTORICA ───────────────────────────────────────────────────────

def _cargar_csv_externo(nombre_archivo):
    """
    Carga un CSV externo desde la carpeta del script (DATOS_CSV/ o raíz).
    Busca en orden: SCRIPT_DIR/DATOS_CSV/, SCRIPT_DIR/, GitHub raw.
    Devuelve DataFrame o None si no se encuentra.
    """
    import io
    candidatos = [
        SCRIPT_DIR / "DATOS_CSV" / nombre_archivo,
        SCRIPT_DIR / nombre_archivo,
    ]
    # Intentar local primero
    for ruta in candidatos:
        if ruta.exists():
            try:
                return pd.read_csv(ruta)
            except Exception as e:
                print(f"  ! {nombre_archivo} local error: {e}")

    # Fallback: GitHub raw (mismo repo que los JSON)
    base_github = "https://raw.githubusercontent.com/ManULoreN14/nq-proxy/main/"
    try:
        r = requests.get(base_github + nombre_archivo, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f"  ! {nombre_archivo} GitHub error: {e}")
    return None


def similitud_historica_v2(
    rsi_v, vix_v, vix_ch3d, roc5d_v, breadth_v, dist_v,
    vvix_v=None, skew_v=None, dix_v=None, gex_v=None,
    spread_vix_pct_v=None, dist_sma200_v=None
):
    """
    kNN multivariable v2 — Predictor de Patrones Históricos enriquecido.

    Compara el fingerprint actual (hasta 12 features) contra todos los días
    del histórico QQQ+VIX (2014-hoy) enriquecidos con DIX, GEX, VVIX y SKEW
    desde los CSVs externos.

    Devuelve distribución de retornos reales NDX a 2/5/10/20d sobre los
    k=50 días más similares, con estadísticas completas.

    Features y pesos:
      spread_vix_pct  2.0  (VIX Term Structure: contango vs backwardation)
      dist_sma200     1.8  (distancia a media 200d: sobreextensión)
      vvix            1.5  (volatilidad de volatilidad)
      dix             1.5  (actividad dark pools / acumulación institucional)
      rsi_ndx         1.2  (momentum técnico)
      roc5d_ndx       1.2  (impulso reciente)
      gex_pct         1.0  (régimen gamma, percentil rolling)
      vvix_vix_ratio  1.5  (régimen de miedo relativo)
      skew            0.8  (put/call OTM skew)
      vix_ch3d        1.0  (aceleración del VIX)
      roc20_ndx       1.0  (momentum 20d)
      breadth         0.8  (amplitud Mag7)
    """
    try:
        print("  [kNN-v2] Cargando histórico QQQ+VIX...")
        qqq_hist = yf.Ticker("QQQ").history(period="max")["Close"]
        vix_hist = yf.Ticker("^VIX").history(period="max")["Close"]
        vix3m_hist = yf.Ticker("^VIX3M").history(period="max")["Close"]

        if qqq_hist.empty or len(qqq_hist) < 500:
            raise ValueError("Histórico QQQ insuficiente")

        # Normalizar índices a tz-naive
        for s in [qqq_hist, vix_hist, vix3m_hist]:
            if s.index.tz is not None:
                s.index = s.index.tz_localize(None)

        base = pd.DataFrame({
            "qqq": qqq_hist,
            "vix": vix_hist,
            "vix3m": vix3m_hist,
        }).dropna(subset=["qqq", "vix"])
        base = base[base.index >= pd.Timestamp("2014-01-01")].copy()

        # ── Cargar CSVs externos (DIX, VVIX, SKEW) ──────────────────────────
        dix_df = _cargar_csv_externo("DIX.csv")
        vvix_df = _cargar_csv_externo("VVIX_History.csv")
        skew_df = _cargar_csv_externo("SKEW_History.csv")

        if dix_df is not None:
            dix_df["_fecha"] = pd.to_datetime(dix_df.get("date", dix_df.columns[0]), errors="coerce")
            dix_df = dix_df.dropna(subset=["_fecha"]).set_index("_fecha")
            if "dix" in dix_df.columns:
                base["dix"] = (dix_df["dix"] * 100).reindex(base.index, method="nearest", tolerance=pd.Timedelta("3d"))
            if "gex" in dix_df.columns:
                base["gex_raw"] = (dix_df["gex"] / 1e9).reindex(base.index, method="nearest", tolerance=pd.Timedelta("3d"))

        if vvix_df is not None:
            col_d = next((c for c in vvix_df.columns if c.upper() in ("DATE", "FECHA")), vvix_df.columns[0])
            col_v = next((c for c in vvix_df.columns if "VVIX" in c.upper()), None)
            if col_v:
                vvix_df["_fecha"] = pd.to_datetime(vvix_df[col_d], errors="coerce")
                vvix_df = vvix_df.dropna(subset=["_fecha"]).set_index("_fecha")
                base["vvix"] = vvix_df[col_v].reindex(base.index, method="nearest", tolerance=pd.Timedelta("3d"))

        if skew_df is not None:
            col_d = next((c for c in skew_df.columns if c.upper() in ("DATE", "FECHA")), skew_df.columns[0])
            col_v = next((c for c in skew_df.columns if "SKEW" in c.upper()), None)
            if col_v:
                skew_df["_fecha"] = pd.to_datetime(skew_df[col_d], errors="coerce")
                skew_df = skew_df.dropna(subset=["_fecha"]).set_index("_fecha")
                base["skew"] = skew_df[col_v].reindex(base.index, method="nearest", tolerance=pd.Timedelta("3d"))

        print(f"  [kNN-v2] Base enriquecida: {len(base)} días | cols: {[c for c in base.columns if base[c].notna().sum() > 100]}")

        # ── Feature engineering ──────────────────────────────────────────────
        qqq_s = base["qqq"].ffill()
        vix_s = base["vix"].ffill()
        vix3m_s = base["vix3m"].ffill()

        # VIX term structure
        base["spread_vix_pct"] = (vix3m_s - vix_s) / vix_s.replace(0, np.nan) * 100

        # RSI14
        d = qqq_s.diff()
        g = d.clip(lower=0).ewm(com=13, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(com=13, adjust=False).mean()
        base["rsi"] = 100 - (100 / (1 + g / l.replace(0, np.nan)))

        # Distancia a SMA200
        sma200 = qqq_s.rolling(200, min_periods=200).mean()
        base["dist_sma200"] = (qqq_s - sma200) / sma200.replace(0, np.nan) * 100

        # Momentum
        base["roc5d"] = qqq_s.pct_change(5) * 100
        base["roc20d"] = qqq_s.pct_change(20) * 100

        # Aceleración VIX
        base["vix_ch3d"] = vix_s.pct_change(3) * 100

        # VVIX/VIX ratio
        if "vvix" in base.columns:
            base["vvix_vix_ratio"] = base["vvix"] / vix_s.replace(0, np.nan)
        else:
            base["vvix_vix_ratio"] = np.nan

        # GEX percentil rolling 252d
        if "gex_raw" in base.columns:
            base["gex_pct"] = base["gex_raw"].rolling(252, min_periods=63).rank(pct=True) * 100
        else:
            base["gex_pct"] = np.nan

        # Sprint 3 C.2: ANTES había una feature "breadth" que se asignaba COMO
        # CONSTANTE (valor de HOY a todas las filas históricas). Eso significaba
        # que la feature tenía peso 0.8 pero NO aportaba información (todas las
        # diferencias eran 0). Ahora se elimina del conjunto de features.

        # Añadir columnas opcionales con NaN si no están disponibles
        # (SKEW puede faltar si el CSV no existe — el kNN lo tolera con thresh=0.55)
        for _opt_col in ["skew", "dix", "gex_pct", "vvix", "vvix_vix_ratio"]:
            if _opt_col not in base.columns:
                base[_opt_col] = np.nan

        # Eliminar filas con demasiados NaN en features core
        # Sprint 3 C.2: "breadth" eliminada del conjunto (era constante = información 0)
        feat_df = base[[
            "spread_vix_pct", "dist_sma200", "vvix", "vvix_vix_ratio",
            "dix", "gex_pct", "skew", "rsi", "roc5d", "roc20d",
            "vix_ch3d",
        ]].copy()

        # ── Normalización Z-score rolling 504d ───────────────────────────────
        feat_norm = pd.DataFrame(index=feat_df.index)
        for col in feat_df.columns:
            s = feat_df[col]
            rm = s.rolling(504, min_periods=100).mean()
            rs = s.rolling(504, min_periods=100).std().replace(0, np.nan)
            feat_norm[col] = ((s - rm) / rs).clip(-4, 4)

        feat_norm = feat_norm.dropna(thresh=int(len(feat_norm.columns) * 0.55))

        if len(feat_norm) < 200:
            raise ValueError(f"Insuficientes días normalizados: {len(feat_norm)}")

        # ── Fingerprint del día actual ────────────────────────────────────────
        cols_order = list(feat_norm.columns)

        # Valores actuales: usar los pasados como parámetros; fallback = última fila
        ultima = feat_norm.iloc[-1]

        def _safe_z(col_name, valor_raw):
            """Normaliza un valor raw al z-score de esa columna."""
            if valor_raw is None or (isinstance(valor_raw, float) and np.isnan(valor_raw)):
                return float(ultima[col_name]) if col_name in ultima.index else 0.0
            s = feat_df[col_name].dropna() if col_name in feat_df.columns else pd.Series()
            if len(s) < 50:
                return 0.0
            mean_val = s.rolling(504, min_periods=100).mean().iloc[-1]
            std_val = s.rolling(504, min_periods=100).std().iloc[-1]
            if np.isnan(mean_val) or np.isnan(std_val) or std_val == 0:
                return 0.0
            return float(np.clip((valor_raw - mean_val) / std_val, -4, 4))

        # Construir el vector del fingerprint actual
        # (usa valores externos si vienen, si no usa la última fila normalizada)
        # Sprint 3 C.2: "breadth" eliminado (era constante = información 0)
        hoy_vec = np.array([
            _safe_z("spread_vix_pct", spread_vix_pct_v),
            _safe_z("dist_sma200", dist_sma200_v or dist_v),
            _safe_z("vvix", vvix_v),
            _safe_z("vvix_vix_ratio", (vvix_v / vix_v) if (vvix_v and vix_v) else None),
            _safe_z("dix", dix_v),
            _safe_z("gex_pct", None),   # siempre desde histórico
            _safe_z("skew", skew_v),
            _safe_z("rsi", rsi_v),
            _safe_z("roc5d", roc5d_v),
            _safe_z("roc20d", None),    # desde histórico
            _safe_z("vix_ch3d", vix_ch3d),
        ], dtype=float)

        # ── Pesos ─────────────────────────────────────────────────────────────
        # Sprint 3 C.2: peso de "breadth" (0.8) eliminado del array
        PESOS = np.array([
            2.0,  # spread_vix_pct
            1.8,  # dist_sma200
            1.5,  # vvix
            1.5,  # vvix_vix_ratio
            1.5,  # dix
            1.0,  # gex_pct
            0.8,  # skew
            1.2,  # rsi
            1.2,  # roc5d
            1.0,  # roc20d
            1.0,  # vix_ch3d
        ], dtype=float)

        vals = feat_norm[cols_order].values
        n_total = len(vals)

        # ── kNN: distancia euclidiana ponderada ───────────────────────────────
        lookahead_max = 22   # días hábiles (~1 mes)
        exclude_tail = lookahead_max + 5
        cands_vals = vals[:-exclude_tail]
        cands_dates = feat_norm.index[:-exclude_tail]

        # Sustituir NaN por 0 antes de calcular distancias
        # (features ausentes no penalizan ni distorsionan)
        hoy_clean   = np.where(np.isnan(hoy_vec), 0.0, hoy_vec)
        cands_clean = np.where(np.isnan(cands_vals), 0.0, cands_vals)

        diffs = (cands_clean - hoy_clean) * np.sqrt(PESOS)
        dists = np.sqrt((diffs ** 2).sum(axis=1))
        max_d = float(np.nanmax(dists)) if np.nanmax(dists) > 0 else 1.0
        sims  = 1.0 - dists / max_d

        K = 50
        idx_top = np.argsort(-sims)

        # ── Calcular retornos reales para cada vecino ─────────────────────────
        qqq_vals = base["qqq"].reindex(feat_norm.index).ffill().values
        fechas_all = feat_norm.index

        vecinos_sel = []
        for i in idx_top:
            if len(vecinos_sel) >= K:
                break
            fecha_i = cands_dates[i]
            pos_global = np.searchsorted(fechas_all, fecha_i)

            # Retornos a 2/5/10/20 días hábiles
            rets = {}
            qqq_base = qqq_vals[pos_global] if pos_global < len(qqq_vals) else None
            if qqq_base is None or np.isnan(qqq_base) or qqq_base == 0:
                continue

            for h, label in [(2, "2d"), (5, "5d"), (10, "10d"), (20, "20d")]:
                pos_fut = pos_global + h
                if pos_fut < len(qqq_vals):
                    v_fut = qqq_vals[pos_fut]
                    if not np.isnan(v_fut):
                        rets[label] = round((v_fut / qqq_base - 1) * 100, 2)

            if len(rets) < 3:
                continue

            vecinos_sel.append({
                "fecha": fecha_i.strftime("%Y-%m-%d"),
                "similitud": round(float(sims[i]), 4),
                "rets": rets,
            })

        if len(vecinos_sel) < 10:
            raise ValueError(f"Pocos vecinos válidos: {len(vecinos_sel)}")

        # ── Estadísticas de distribución de retornos ─────────────────────────
        def _stats_horizonte(label):
            vals_h = [v["rets"][label] for v in vecinos_sel if label in v["rets"]]
            if len(vals_h) < 5:
                return None
            a = np.array(vals_h)
            pct_pos = round(float((a > 0).mean() * 100), 1)
            pct_neg = round(float((a < 0).mean() * 100), 1)
            return {
                "n": len(a),
                "media": round(float(a.mean()), 2),
                "mediana": round(float(np.median(a)), 2),
                "p10": round(float(np.percentile(a, 10)), 2),
                "p25": round(float(np.percentile(a, 25)), 2),
                "p75": round(float(np.percentile(a, 75)), 2),
                "p90": round(float(np.percentile(a, 90)), 2),
                "pct_positivo": pct_pos,
                "pct_negativo": pct_neg,
                "max": round(float(a.max()), 2),
                "min": round(float(a.min()), 2),
            }

        stats_2d  = _stats_horizonte("2d")
        stats_5d  = _stats_horizonte("5d")
        stats_10d = _stats_horizonte("10d")
        stats_20d = _stats_horizonte("20d")

        # ── Clasificación de similitud a escenarios tipo ──────────────────────
        # Basado en retorno mediano esperado a 5d y % positivo
        med5 = stats_5d["mediana"] if stats_5d else 0
        pct5 = stats_5d["pct_positivo"] if stats_5d else 50

        if pct5 >= 65 and med5 >= 0.8:
            escenario_tipo = "alcista_fuerte"
            escenario_desc = "Patrón alcista: la mayoría de análogos subió >0.8% en 5d"
        elif pct5 >= 55 and med5 >= 0.2:
            escenario_tipo = "consolidacion"
            escenario_desc = "Consolidación con sesgo alcista: más subidas que bajadas pero moderadas"
        elif pct5 <= 35 and med5 <= -0.8:
            escenario_tipo = "bajista"
            escenario_desc = "Patrón bajista: la mayoría de análogos bajó en 5d"
        elif pct5 <= 45 and med5 <= -0.3:
            escenario_tipo = "techo_mercado"
            escenario_desc = "Patrón de techo o corrección: sesgo bajista en análogos históricos"
        elif pct5 >= 55 and med5 >= 0 and (stats_5d["p10"] if stats_5d else 0) < -2.5:
            escenario_tipo = "suelo_panico"
            escenario_desc = "Zona de pánico/suelo: sesgo alcista pero con cola bajista asimétrica"
        else:
            escenario_tipo = "neutro"
            escenario_desc = "Patrón sin sesgo claro: análogos mixtos sin dirección dominante"

        # ── Interpretación automática ─────────────────────────────────────────
        mejor_sim = vecinos_sel[0]["similitud"] if vecinos_sel else 0.0
        fiable = mejor_sim >= 0.75  # umbral para similitud real (z-score euclidiana)

        if stats_5d:
            s5 = stats_5d
            interp = (
                f"{len(vecinos_sel)} análogos históricos. "
                f"NDX +{s5['media']:.1f}% medio a 5d ({s5['pct_positivo']:.0f}% positivo, "
                f"mediana {s5['mediana']:+.1f}%). "
                f"Rango P10/P90: [{s5['p10']:+.1f}%, {s5['p90']:+.1f}%]."
            )
        else:
            interp = f"{len(vecinos_sel)} análogos encontrados. Datos insuficientes para estadísticas."

        # ── Top 10 vecinos para el dashboard ─────────────────────────────────
        top10 = [
            {
                "fecha": v["fecha"],
                "similitud": v["similitud"],
                "ret_2d": v["rets"].get("2d"),
                "ret_5d": v["rets"].get("5d"),
                "ret_10d": v["rets"].get("10d"),
                "ret_20d": v["rets"].get("20d"),
                # Categoría de corrección (compatibilidad con Fase 8 frontend)
                "caida_max_20d": v["rets"].get("20d", 0),
                "categoria": (
                    "ruido" if abs(v["rets"].get("20d", 0)) < 3 else
                    "leve" if abs(v["rets"].get("20d", 0)) < 5 else
                    "moderada" if abs(v["rets"].get("20d", 0)) < 10 else
                    "fuerte" if abs(v["rets"].get("20d", 0)) < 20 else "crash"
                ),
            }
            for v in vecinos_sel[:10]
        ]

        # Distribución de categorías (compatibilidad con Fase 8 existente)
        descs = {
            "ruido": "Sin caída (<3%)", "leve": "Leve (3-5%)",
            "moderada": "Moderada (5-10%)", "fuerte": "Fuerte (10-20%)", "crash": "Crash (>20%)",
        }
        distribucion = {}
        n_vec = len(vecinos_sel)
        for cat, desc in descs.items():
            n_cat = sum(1 for v in top10 if v["categoria"] == cat)
            # Usar los 50 vecinos para la distribución real
            n_cat_full = sum(
                1 for v in vecinos_sel
                if abs(v["rets"].get("20d", 0)) < (3 if cat == "ruido" else
                       5 if cat == "leve" else 10 if cat == "moderada" else
                       20 if cat == "fuerte" else 999)
                and abs(v["rets"].get("20d", 0)) >= (0 if cat == "ruido" else
                        3 if cat == "leve" else 5 if cat == "moderada" else
                        10 if cat == "fuerte" else 20)
            )
            distribucion[cat] = {
                "porcentaje": round(n_cat_full / n_vec * 100, 1) if n_vec else 0,
                "n": n_cat_full,
                "descripcion": desc,
            }

        print(f"  [kNN-v2] OK: {len(vecinos_sel)} vecinos | mejor_sim={mejor_sim:.3f} | "
              f"5d media={stats_5d['media'] if stats_5d else '?'}% "
              f"({stats_5d['pct_positivo'] if stats_5d else '?'}% pos)")

        return {
            "version": "2.0",
            "generado": utcnow_str(),
            "fecha_referencia": datetime.date.today().isoformat(),
            "n_vecinos": len(vecinos_sel),
            "n_dias_historico": n_total,
            "ventana_historico": "2014-hoy",
            "fiable": fiable,
            "mejor_similitud": round(mejor_sim, 4),
            "escenario_tipo": escenario_tipo,
            "escenario_desc": escenario_desc,
            "interpretacion": interp,
            "fingerprint_hoy": {
                "spread_vix_pct": round(spread_vix_pct_v, 2) if spread_vix_pct_v is not None else None,
                "dist_sma200": round(dist_sma200_v or dist_v or 0, 2),
                "vvix": vvix_v,
                "dix": dix_v,
                "skew": skew_v,
                "rsi_ndx": rsi_v,
                "roc5d": roc5d_v,
                "vix": vix_v,
                "vix_ch3d_pct": round(vix_ch3d or 0, 2),
            },
            "config": {
                "k_vecinos": K,
                "horizonte_dias": lookahead_max,
                "n_dias_base": n_total,
                "similitud_minima_fiable": 0.75,
                "pesos": {
                    "spread_vix_pct": 2.0, "dist_sma200": 1.8, "vvix": 1.5,
                    "vvix_vix_ratio": 1.5, "dix": 1.5, "gex_pct": 1.0,
                    "skew": 0.8, "rsi": 1.2, "roc5d": 1.2, "roc20d": 1.0,
                    "vix_ch3d": 1.0, "breadth": 0.8,
                },
                "features_csv": ["dix", "gex", "vvix", "skew"],
            },
            "retornos": {
                "2d": stats_2d,
                "5d": stats_5d,
                "10d": stats_10d,
                "20d": stats_20d,
            },
            "distribucion": distribucion,
            "vecinos_top10": top10,
        }

    except Exception as e:
        print(f"  ! kNN-v2: {e}")
        import traceback; traceback.print_exc()
        # Fallback: intentar cargar del JSON anterior si existe
        if OUTPUT_FILE.exists():
            try:
                old = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
                sim = old.get("similitud_historica", {})
                if sim.get("version") == "2.0":
                    sim["generado"] = utcnow_str()
                    sim["_cache"] = True
                    return sim
            except Exception:
                pass
        return {
            "version": "2.0", "fiable": False, "n_vecinos": 0,
            "generado": utcnow_str(),
            "fecha_referencia": datetime.date.today().isoformat(),
            "interpretacion": f"No disponible: {e}",
            "escenario_tipo": "sin_datos",
            "escenario_desc": "Sin datos históricos.",
            "distribucion": {},
            "vecinos_top10": [],
        }


# ─────────────────────────────────────────────────────────────────────────────
#  LEGACY WRAPPER — mantiene compatibilidad con la llamada original de run()
# ─────────────────────────────────────────────────────────────────────────────
def similitud_historica(rsi_v, vix_v, vix_ch3d, roc5d_v, breadth_v, dist_v):
    """
    Wrapper legacy — delega en similitud_historica_v2 con los parámetros
    disponibles. Los parámetros enriquecidos (vvix, skew, dix, gex) se
    cargan internamente desde los CSVs externos en la v2.
    """
    return similitud_historica_v2(
        rsi_v=rsi_v,
        vix_v=vix_v,
        vix_ch3d=vix_ch3d,
        roc5d_v=roc5d_v,
        breadth_v=breadth_v,
        dist_v=dist_v,
        # Los parámetros enriquecidos se cargan desde CSV en la v2
        vvix_v=None, skew_v=None, dix_v=None, gex_v=None,
        spread_vix_pct_v=None, dist_sma200_v=None,
    )

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def run():
    now=datetime.datetime.now(datetime.timezone.utc)
    today=datetime.date.today().isoformat()
    print(f"\n{'='*60}\n  MOTOR MANENGIS v2.4  --  {now.strftime('%Y-%m-%d %H:%M UTC')}\n  FRED key: {FRED_API_KEY[:8]}...\n{'='*60}\n")

    print("Precios...")
    qqq=get_hist("QQQ","90d"); ndx=get_hist("^NDX","30d")
    vix=get_hist("^VIX","30d"); v3m=get_hist("^VIX3M","10d")
    p_qqq=last_val(qqq); p_ndx=last_val(ndx); p_vix=last_val(vix); p_v3m=last_val(v3m)
    print(f"  QQQ={p_qqq}  NDX={p_ndx}  VIX={p_vix}  VIX3M={p_v3m}")

    print("Tecnicos...")
    rsi_v=calc_rsi(qqq); ema20_v=calc_ema(qqq,20); ema50_v=calc_ema(qqq,50); atr_v=calc_atr("QQQ")
    roc5d_v=p_hace5=None
    if qqq is not None and len(qqq)>=6:
        p_hace5=round(float(qqq.iloc[-6]),2)
        roc5d_v=round((float(qqq.iloc[-1])-p_hace5)/p_hace5*100,2)
    max60_v=dist_max=min90_v=None
    if qqq is not None and len(qqq)>=10:
        max60_v=round(float(qqq.rolling(60).max().iloc[-1]),2)
        min90_v=round(float(qqq.min()),2)
        dist_max=round((p_qqq-max60_v)/max60_v*100,2) if p_qqq else None
    print(f"  RSI={rsi_v}  EMA20={ema20_v}  EMA50={ema50_v}  ROC5d={roc5d_v}%")

    print("VIX Term Structure...")
    vts_ratio=vts_spread=vix_ch3d=None; vts_back=False; vts_est="sin_datos"; vts_desc="Sin datos"
    if p_vix and p_v3m:
        vts_ratio=round(p_vix/p_v3m,4); vts_spread=round(p_v3m-p_vix,2); vts_back=p_vix>p_v3m
        # Clasificación correcta del contango:
        #   ratio < 0.85  → contango profundo (curva muy empinada, calma extrema)
        #   ratio 0.85-1  → contango normal
        #   ratio > 1     → backwardation (capturado por vts_back)
        if vts_back:
            vts_est = "backwardation"
        elif vts_ratio < 0.85:
            vts_est = "contango_profundo"
        else:
            vts_est = "contango_normal"
        vts_desc=f"VIX ({p_vix}) {'>' if vts_back else '<'} VIX3M ({p_v3m}): {vts_est}"
    if vix is not None and len(vix)>=4:
        vn=float(vix.iloc[-1]); v3d=float(vix.iloc[-4])
        vix_ch3d=round((vn-v3d)/v3d*100,2) if v3d else None
    print(f"  {vts_est} | spread={vts_spread} | ch3d={vix_ch3d}%")

    print("COT NQ + VIX (ZIP CFTC)...")
    try:
        cot_nq_d = cot_nq()
    except Exception as e:
        print(f"  ! cot_nq() crash: {e}")
        import traceback; traceback.print_exc()
        cot_nq_d = {"error": f"crash: {e}"}
    try:
        cot_vix_d = cot_vix()
    except Exception as e:
        print(f"  ! cot_vix() crash: {e}")
        import traceback; traceback.print_exc()
        cot_vix_d = {"error": f"crash: {e}"}
    lev_net=cot_nq_d.get("leveraged_net") if isinstance(cot_nq_d,dict) else None
    cot_sesgo=cot_nq_d.get("sesgo","sin_datos") if isinstance(cot_nq_d,dict) else "sin_datos"
    cot_fecha=cot_nq_d.get("fecha_reporte","?") if isinstance(cot_nq_d,dict) else "?"
    print(f"  NQ: net={lev_net} sesgo={cot_sesgo} fecha={cot_fecha}")
    print(f"  VIX: {cot_vix_d.get('senal','?') if isinstance(cot_vix_d,dict) else '?'}")

    print("PCR CBOE (OPTIONS_VOLUME_REPORT)...")
    try:
        pcr_d = pcr_cboe()
    except Exception as e:
        print(f"  ! pcr_cboe() crash: {e}")
        pcr_d = {"error": f"crash: {e}"}
    print(f"  PCR Total={pcr_d.get('total','?')} Equity={pcr_d.get('equity','?')} fecha={pcr_d.get('fecha','?')}")

    # ── Breadth: dos métricas complementarias ─────────────────────────────────
    # 1) Breadth Mag7 (EMA20/50) — local, cálculo propio
    # 2) Breadth NDX100 New Highs/Lows 52w — leído de datos_radar.json si existe
    # Son MÉTRICAS DIFERENTES, no intercambiables:
    #   · Mag7 EMA20/50 mide momentum corto plazo de las 7 mega-caps
    #   · NDX100 NH/NL mide amplitud estructural 52w sobre los 100 componentes
    print("Breadth Mag7 (EMA20/50)...")
    br = calcular_breadth(MAG7)
    br["fuente"] = "Mag7_local"
    br_pct20 = br["pct_sobre_ema20"]
    br_pct50 = br["pct_sobre_ema50"]
    br_div   = br["divergencia"]
    print(f"  EMA20={br_pct20}%  EMA50={br_pct50}%  div={br_div}")

    # Señal adicional NDX100 desde radar (si el cron del radar corrió antes)
    ndx100_breadth_signal = None
    _radar_json_path = SCRIPT_DIR / "datos_radar.json"
    if _radar_json_path.exists():
        try:
            _rd = json.loads(_radar_json_path.read_text(encoding="utf-8"))
            _ndx_b = _rd.get("amplitud_mercado", {}).get("ndx100_breadth", {})
            if _ndx_b and not _ndx_b.get("error"):
                ndx100_breadth_signal = {
                    "new_highs_52w": _ndx_b.get("new_highs_52w"),
                    "new_lows_52w":  _ndx_b.get("new_lows_52w"),
                    "net_breadth_pct": _ndx_b.get("net_breadth_pct"),
                    "senal": _ndx_b.get("senal"),
                    "score": _ndx_b.get("score"),
                    "fuente": "NDX100_radar",
                }
                print(f"  NDX100 NH/NL={ndx100_breadth_signal.get('net_breadth_pct')}% "
                      f"señal={ndx100_breadth_signal.get('senal')}")
            else:
                print(f"  NDX100 breadth no disponible en radar (error: {_ndx_b.get('error') if _ndx_b else 'sin campo'})")
        except Exception as _e:
            print(f"  ! lectura ndx100_breadth radar: {_e}")

    print("FRED (API JSON con clave)...")
    ff_v,ff_p   = fred_series("DFF")
    u2_v,u2_p   = fred_series("DGS2")
    u10_v,u10_p = fred_series("DGS10")
    u30_v,u30_p = fred_series("DGS30")
    u3m_v,_     = fred_series("DGS3MO")
    cpi_v,_     = fred_series("CPIAUCSL")
    pce_v,_     = fred_series("PCEPILFE")
    bal_v,bal_p = fred_series("WALCL")
    m2_v,_      = fred_series("M2SL")
    umc_v,umc_p = fred_series("UMCSENT")
    nfci_v,_    = fred_series("NFCI")
    sp_2_10 =round(u10_v-u2_v,4) if u10_v and u2_v else None
    sp_3m_10=round(u10_v-u3m_v,4) if u10_v and u3m_v else None
    inv=sp_2_10 is not None and sp_2_10<0
    print(f"  FF={ff_v}% | 10Y={u10_v}% | spread={sp_2_10} | NFCI={nfci_v}")

    print("Fear & Greed...")
    fg=fear_greed()
    print(f"  F&G={fg['score']} ({fg['estado']}) fuente={fg.get('fuente')}")

    # ── Sprint 3 C.1: PRIORIZAR el kNN del radar (radar corre antes) ────
    # Antes el motor hacía su propio kNN duplicando trabajo (~30s/noche).
    # Ahora intenta leer datos_radar.knn_predictor primero. Si no existe o
    # falla, recurre al cálculo propio como fallback.
    print("Similitud histórica (kNN — preferir radar, fallback local)...")
    sim = None
    _knn_radar_used = False
    _radar_knn_path = SCRIPT_DIR / "datos_radar.json"
    if _radar_knn_path.exists():
        try:
            _rd_knn = json.loads(_radar_knn_path.read_text(encoding="utf-8"))
            _knn_r = _rd_knn.get("knn_predictor", {})
            if _knn_r and not _knn_r.get("error") and _knn_r.get("n_vecinos", 0) >= 10:
                # Mapear al formato esperado (compatible con similitud_historica_v2)
                sim = {
                    "version":           _knn_r.get("version", "1.0"),
                    "generado":          _knn_r.get("generado"),
                    "fecha_referencia":  _knn_r.get("fecha_referencia"),
                    "n_vecinos":         _knn_r.get("n_vecinos"),
                    "n_dias_historico":  _knn_r.get("n_dias_historico"),
                    "ventana_historico": _knn_r.get("ventana_historico"),
                    "fiable":            _knn_r.get("fiable"),
                    "mejor_similitud":   _knn_r.get("mejor_similitud"),
                    "escenario_tipo":    _knn_r.get("escenario_tipo"),
                    "escenario_desc":    _knn_r.get("escenario_desc"),
                    "interpretacion":    _knn_r.get("interpretacion"),
                    "config":            _knn_r.get("config", {}),
                    "retornos":          _knn_r.get("retornos", {}),
                    "distribucion":      _knn_r.get("distribucion", {}),
                    "vecinos_top10":     _knn_r.get("vecinos_top10", []),
                    "fuente":            "radar.knn_predictor",
                }
                _knn_radar_used = True
                print(f"  ✓ kNN leído del radar: {sim['n_vecinos']} vecinos · escenario={sim['escenario_tipo']}")
        except Exception as _e:
            print(f"  ! kNN radar: {_e}")

    if not _knn_radar_used:
        print("  ↪ fallback: calculando kNN local con similitud_historica_v2")
        _spread_vix_pct = None
        if p_vix and p_v3m and p_vix > 0:
            _spread_vix_pct = round((p_v3m - p_vix) / p_vix * 100, 2)
        _dist_sma200 = None
        if qqq is not None and len(qqq) >= 200:
            _sma200_val = float(qqq.rolling(200).mean().iloc[-1])
            if _sma200_val and _sma200_val > 0 and p_qqq:
                _dist_sma200 = round((p_qqq - _sma200_val) / _sma200_val * 100, 2)
        sim = similitud_historica_v2(
            rsi_v=rsi_v, vix_v=p_vix, vix_ch3d=vix_ch3d,
            roc5d_v=roc5d_v, breadth_v=br_pct50, dist_v=dist_max,
            spread_vix_pct_v=_spread_vix_pct, dist_sma200_v=_dist_sma200,
            vvix_v=None, skew_v=None, dix_v=None, gex_v=None,
        )
        sim["fuente"] = "motor_local_fallback"
    print(f"  version={sim.get('version')} | fiable={sim.get('fiable')} | mejor_sim={sim.get('mejor_similitud')} | escenario={sim.get('escenario_tipo')} | fuente={sim.get('fuente')}")
    if sim.get("retornos", {}).get("5d"):
        s5 = sim["retornos"]["5d"]
        print(f"  5d: media={s5['media']}% | mediana={s5['mediana']}% | pos={s5['pct_positivo']}%")

    # ── Puente con Radar + señales reales adicionales para risk_score ─────────
    # Sprint 6: formalizamos 3 fuentes que YA se generaban pero no influian
    # en el risk_score de Manengis:
    #   1. score_avg de Radar (ya se leia mas abajo para el historico, pero
    #      nunca se usaba como factor de riesgo — ahora si).
    #   2. PCR percentil historico real (PCR.txt + PCR_RATIOS_HISTORICO.csv).
    #   3. VIX Term Structure real por futuros (VIX.txt), en vez de solo el
    #      ratio spot VIX/VIX3M — gradua el factor de backwardation por
    #      severidad real en vez de sumar +2.0 fijo siempre que vts_back.
    score_avg_radar_temprano = None
    try:
        _radar_json_temprano = SCRIPT_DIR / "datos_radar.json"
        if _radar_json_temprano.exists():
            _rd_temp = json.loads(_radar_json_temprano.read_text(encoding="utf-8"))
            _hor_temp = _rd_temp.get("scores", {}).get("horizontes", {})
            _vals_temp = [v.get("score") for v in _hor_temp.values() if v.get("score") is not None]
            if _vals_temp:
                score_avg_radar_temprano = round(sum(_vals_temp) / len(_vals_temp), 2)
    except Exception as _e3:
        print(f"  ! score_avg_radar (bridge): {_e3}")

    pcr_pctl_manengis = None
    try:
        _pcr_txt_path = SCRIPT_DIR / "PCR.txt"
        _pcr_hist_path = SCRIPT_DIR / "DATOS_CSV" / "PCR_RATIOS_HISTORICO.csv"
        if _pcr_txt_path.exists() and _pcr_hist_path.exists():
            _pcr_total_hoy = None
            for _ln in _pcr_txt_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if _ln.strip().startswith("TOTAL PUT/CALL RATIO"):
                    _tok = _ln.split("\t")[-1].strip()
                    try:
                        _pcr_total_hoy = float(_tok)
                    except ValueError:
                        pass
                    break
            if _pcr_total_hoy is not None:
                import csv as _csv_mod
                _serie_pcr = []
                with open(_pcr_hist_path, newline="", encoding="utf-8", errors="replace") as _f:
                    for _row in _csv_mod.DictReader(_f):
                        try:
                            _v = float(_row.get("TOTAL_PUT_CALL_RATIO", ""))
                            if 0.1 <= _v <= 3.0:
                                _serie_pcr.append(_v)
                        except (ValueError, TypeError):
                            pass
                if len(_serie_pcr) >= 60:
                    pcr_pctl_manengis = round(
                        sum(1 for _x in _serie_pcr if _x <= _pcr_total_hoy) / len(_serie_pcr) * 100, 1)
    except Exception as _e4:
        print(f"  ! PCR percentil (bridge): {_e4}")

    vts_spread_pct_real = None
    try:
        _vix_txt_path = SCRIPT_DIR / "VIX.txt"
        if _vix_txt_path.exists() and p_vix:
            _front_precio = None
            for _ln in _vix_txt_path.read_text(encoding="utf-8", errors="replace").splitlines():
                _partes = _ln.strip().split("\t")
                if len(_partes) < 7:
                    continue
                if _partes[0] == "VIX":
                    continue
                if _partes[0].startswith("VX") and "/" in _partes[0] and not _partes[0][2].isdigit():
                    # contrato mensual estandar (VX/M6, no VX23/M6 semanal)
                    try:
                        _front_precio = float(_partes[6])
                    except (ValueError, IndexError):
                        pass
                    break
            if _front_precio:
                vts_spread_pct_real = round((_front_precio - p_vix) / p_vix * 100, 1)
    except Exception as _e5:
        print(f"  ! VTS real (bridge): {_e5}")

    factores=[]; risk=0.0
    if rsi_v:
        if rsi_v>75:   risk+=1.5; factores.append(f"RSI={rsi_v} sobrecompra extrema")
        elif rsi_v>70: risk+=1.0; factores.append(f"RSI={rsi_v} sobrecompra")
    if p_vix:
        if p_vix>28:   risk+=2.0; factores.append(f"VIX={p_vix} zona panico")
        elif p_vix>22: risk+=1.5; factores.append(f"VIX={p_vix} zona alerta")
        elif p_vix<13: risk+=0.5; factores.append(f"VIX={p_vix} complacencia extrema")
    if vts_spread_pct_real is not None:
        # Graduado con la curva real de futuros VIX (VIX.txt), no solo binario
        if vts_spread_pct_real < -10:
            risk += 3.0; factores.append(f"Backwardation fuerte futuros VIX ({vts_spread_pct_real:+.1f}%)")
        elif vts_spread_pct_real < 0:
            risk += 2.0; factores.append(f"Backwardation futuros VIX ({vts_spread_pct_real:+.1f}%)")
        elif vts_spread_pct_real > 25:
            risk += 0.5; factores.append(f"Contango extremo futuros VIX ({vts_spread_pct_real:+.1f}%) — complacencia")
    elif vts_back:
        risk+=2.0; factores.append("VIX Term Structure backwardation")
    if inv:      risk+=1.0; factores.append("Curva tipos invertida 10Y-2Y")
    if fg["score"] and fg["score"]>80: risk+=1.0; factores.append(f"F&G={fg['score']} euforia extrema")
    if cot_sesgo=="bajista": risk+=0.5; factores.append("COT specs muy largos NQ")
    if br_div: risk+=0.5; factores.append("Breadth Mag7 debil vs precio")
    # Señal adicional NDX100 (cuando está disponible desde el radar)
    if ndx100_breadth_signal:
        _ndx_senal = ndx100_breadth_signal.get("senal")
        if _ndx_senal == "bajista_fuerte":
            risk += 1.0
            factores.append(f"Breadth NDX100 muy debil ({ndx100_breadth_signal.get('net_breadth_pct')}%)")
        elif _ndx_senal == "bajista":
            risk += 0.5
            factores.append(f"Breadth NDX100 negativa ({ndx100_breadth_signal.get('net_breadth_pct')}%)")
    if nfci_v and nfci_v>0.1: risk+=0.5; factores.append(f"NFCI={nfci_v} condiciones tensas")

    # PCR percentil histórico real (señal contraria, misma metodología que COT)
    if pcr_pctl_manengis is not None:
        if pcr_pctl_manengis <= 10:
            risk += 1.0; factores.append(f"PCR percentil p{pcr_pctl_manengis} — euforia extrema histórica")
        elif pcr_pctl_manengis <= 25:
            risk += 0.5; factores.append(f"PCR percentil p{pcr_pctl_manengis} — complacencia")
        elif pcr_pctl_manengis >= 90:
            risk -= 0.5; factores.append(f"PCR percentil p{pcr_pctl_manengis} — miedo extremo histórico (contrarian alcista)")

    # Puente con Radar: si el score multi-horizonte de Radar es claramente
    # bajista, sube el riesgo de Manengis; si es claramente alcista, lo baja
    # un poco. Antes se calculaba pero nunca se usaba (Opcion B acordada).
    if score_avg_radar_temprano is not None:
        if score_avg_radar_temprano <= -2:
            risk += 1.0; factores.append(f"Radar score_avg={score_avg_radar_temprano} — bajista")
        elif score_avg_radar_temprano <= -1:
            risk += 0.5; factores.append(f"Radar score_avg={score_avg_radar_temprano} — bajista moderado")
        elif score_avg_radar_temprano >= 2:
            risk -= 0.5; factores.append(f"Radar score_avg={score_avg_radar_temprano} — alcista")

    # ── Sprint 1 B.1: FACTORES REDUCTORES ──────────────────────────────
    # Antes el risk_score solo tenía factores aditivos. Imposible llegar a verde
    # (<3.5) sin que TODOS los factores fueran inactivos a la vez. Sesgo permanente
    # hacia amarillo/naranja. Ahora se restan puntos cuando hay señales positivas
    # confirmadas (mínimo del risk = 0).
    if p_qqq is not None and ema20_v and ema50_v:
        # Tendencia alcista clara: precio > EMA20 > EMA50
        if p_qqq > ema20_v > ema50_v:
            risk -= 0.5
            factores.append(f"Tendencia alcista (precio>EMA20>EMA50)")
    if br_pct50 is not None and br_pct50 > 80:
        # Breadth fuerte: más del 80% de Mag7 sobre EMA50
        risk -= 0.5
        factores.append(f"Breadth Mag7 fuerte ({br_pct50}% sobre EMA50)")
    if roc5d_v is not None and roc5d_v > 2:
        # Momentum positivo confirmado
        risk -= 0.3
        factores.append(f"Momentum 5d positivo (+{roc5d_v}%)")
    if sp_2_10 is not None and sp_2_10 > 0.5:
        # Curva claramente positiva (no invertida ni plana)
        risk -= 0.3
        factores.append(f"Curva sana (10Y-2Y={sp_2_10})")
    if p_vix and 14 <= p_vix <= 18:
        # VIX en zona óptima (ni complacencia extrema ni alerta)
        risk -= 0.3
        factores.append(f"VIX={p_vix} zona óptima")

    risk_score=round(max(0.0, min(risk,10.0)),1)
    semaforo=("verde" if risk_score<3.5 else "amarillo" if risk_score<5.5 else
              "naranja" if risk_score<7.5 else "rojo")
    regimen=("tendencia_alcista" if semaforo in("verde","amarillo") and (roc5d_v or 0)>0
             else "distribucion" if semaforo in("rojo","naranja") else "lateral")
    exp_pct=(80 if semaforo=="verde" else 65 if semaforo=="amarillo" else
             45 if semaforo=="naranja" else 20)
    print(f"  Risk={risk_score} | {semaforo} | Exp={exp_pct}%")

    hist30=[]
    if OUTPUT_FILE.exists():
        try: hist30=json.loads(OUTPUT_FILE.read_text(encoding="utf-8")).get("historico_30d",[])
        except: pass
    cutoff=(datetime.date.today()-datetime.timedelta(days=35)).isoformat()
    hist30=[e for e in hist30 if e.get("fecha","")>=cutoff]

    # ── Leer score_avg del Radar desde datos_radar.json (corre antes en el cron)
    _score_avg_radar = None
    _radar_json_path2 = SCRIPT_DIR / "datos_radar.json"
    if _radar_json_path2.exists():
        try:
            _rd2 = json.loads(_radar_json_path2.read_text(encoding="utf-8"))
            _horizontes = _rd2.get("scores", {}).get("horizontes", {})
            _hor_vals = [v.get("score") for v in _horizontes.values() if v.get("score") is not None]
            if _hor_vals:
                _score_avg_radar = round(sum(_hor_vals) / len(_hor_vals), 3)
        except Exception as _e2:
            print(f"  ! score_avg radar: {_e2}")

    hist30=[e for e in hist30 if e.get("fecha")!=today]+[{
        "fecha":today,"risk_score":risk_score,"fear_greed_score":fg["score"],
        "regimen_mercado":regimen,"exposicion_semaforo":semaforo,"exposicion_pct":exp_pct,
        "precio_qqq":p_qqq,"vix":p_vix,"score_avg":_score_avg_radar}]
    hist30.sort(key=lambda e:e.get("fecha",""))

    doc={
        "version":"2.4","generado":utcnow_str(),
        "fuente":"motor_manengis.py / GitHub Actions","modo":"full",
        "variables_crudas":{
            "precio_qqq":p_qqq,"precio_ndx":p_ndx,"vix":p_vix,"rsi":rsi_v,
            "ema20":ema20_v,"ema50":ema50_v,"atr14":atr_v,"roc5d":roc5d_v,"vix3m":p_v3m,
            "vix_ts_ratio":vts_ratio,"vix_ts_backwardation":vts_back,"vix_ts_estado":vts_est,
            "cot_lev_net":lev_net,"cot_sesgo":cot_sesgo,
            "breadth_pct_ema20":br_pct20,"breadth_pct_ema50":br_pct50,"breadth_divergencia":br_div,
            "exposicion_sugerida_pct":exp_pct,"exposicion_semaforo":semaforo,
            "dist_desde_max_pct":dist_max,"fear_greed_score":fg["score"],
            "fear_greed_estado":fg["estado"],"regimen_mercado":regimen,
            "regimen_confianza":100,"risk_score":risk_score,
            "fedfunds":ff_v,"us2y":u2_v,"us10y":u10_v,"us30y":u30_v,
            "spread_2_10":sp_2_10,"spread_3m_10":sp_3m_10,"curva_invertida":inv,
        },
        "tecnicos":{"precio":p_qqq,"rsi14":rsi_v,"ema20":ema20_v,"ema50":ema50_v,
                    "atr14":atr_v,"roc5d":roc5d_v},
        "vix_term_structure":{"vix":p_vix,"vix3m":p_v3m,"ratio":vts_ratio,
            "spread":vts_spread,"backwardation":vts_back,"estado":vts_est,"descripcion":vts_desc},
        "cot":cot_nq_d or {"error":"No disponible"},
        "cot_vix":cot_vix_d or {"error":"No disponible"},
        "breadth":br,
        "ndx100_breadth": ndx100_breadth_signal,   # señal complementaria desde radar
        "fear_greed":fg,
        "risk_compuesto":{"valor":risk_score,
            "estado":("Bajo riesgo" if risk_score<3.5 else
                      "Neutral / Vigilar" if risk_score<5.5 else
                      "Riesgo elevado" if risk_score<7.5 else "Riesgo maximo"),
            "factores":factores},
        "regimen":{"regimen":regimen,"confianza":100,
            "senales":{"precio_sobre_ema20":bool(p_qqq>ema20_v) if ema20_v else None,
                       "precio_sobre_ema50":bool(p_qqq>ema50_v) if ema50_v else None,
                       "ema20_sobre_ema50":bool(ema20_v>ema50_v) if(ema20_v and ema50_v) else None,
                       "rsi":rsi_v,"breadth_pct_ema20":br_pct20}},
        "plan_exposicion":{
            "exposicion_sugerida_pct":exp_pct,"exposicion_base_pct":exp_pct,
            "semaforo":semaforo,
            "estado":("Exposicion plena" if semaforo=="verde" else
                      "Vigilar / reducir leve" if semaforo=="amarillo" else
                      "Reducir significativo" if semaforo=="naranja" else "Modo defensivo"),
            "accion":"Mantener" if semaforo in("verde","amarillo") else "Reducir",
            "dist_desde_max_pct":dist_max,"max_referencia":max60_v,
            "motivos":factores,
            "descripcion":(
                f"Exposicion {exp_pct}%. "
                f"{'Mantener.' if semaforo in('verde','amarillo') else 'Reducir.'} "
                f"{', '.join(factores) if factores else 'Sin senales de ajuste.'}"
            ),
            "barrida_estructural":{"nivel_barrida":min90_v,
                "dist_barrida_pct":round((p_qqq-min90_v)/min90_v*100,2) if(p_qqq and min90_v) else None,
                "zona_barrida":bool(dist_max is not None and dist_max<-15),
                "sesiones_ventana":90}},
        "velocidad":{
            "flags":{"vix_acelerando":bool(vix_ch3d is not None and vix_ch3d>20),
                     "gex_flip_negativo":False,"pcr_sobre_media":False,
                     "aceleracion_riesgo":bool(risk_score>=6)},
            "descripcion":(
                f"{'ACELERACION DE RIESGO.' if risk_score>=6 else 'Sin aceleracion.'} "
                f"VIX {'+' if (vix_ch3d or 0)>=0 else ''}{vix_ch3d or 0}% (3 dias).")},
        "fred":{
            # Curva normal (spread>0) = saludable = score positivo
            # Curva invertida (spread<0) = recesionaria = score negativo
            "score":1 if sp_2_10 and sp_2_10>0 else -1,
            "estado":"normal" if not inv else "alerta_curva",
            "curva_invertida":inv,
            "curva_descripcion":(f"2Y={u2_v}% 10Y={u10_v}% 30Y={u30_v}% | Spread={sp_2_10}"
                                 if u10_v else "Sin datos FRED"),
            "fedfunds":{"valor":ff_v,"anterior":ff_p,"fecha":today},
            "us2y":{"valor":u2_v,"anterior":u2_p},
            "us10y":{"valor":u10_v,"anterior":u10_p},
            "us30y":{"valor":u30_v,"anterior":u30_p},
            "spread_2_10":{"valor":sp_2_10},"spread_3m_10":{"valor":sp_3m_10},
            "cpi_yoy":{"valor":cpi_v},"core_pce":{"valor":pce_v},
            "balance_fed":{"valor":bal_v,"anterior":bal_p},
            "m2":{"valor":m2_v},"umcsent":{"valor":umc_v,"anterior":umc_p},
            "nfci":{"valor":nfci_v},
            "senales":[
                {"ind":"Fed Funds Rate","val":f"{ff_v}%","tend":"estable","senal":"neutro",
                 "desc":"Tipo de intervencion Fed."},
                {"ind":"Curva 10Y-2Y",
                 "val":f"{'+' if(sp_2_10 or 0)>=0 else ''}{sp_2_10}%","tend":"estable",
                 "senal":"alcista" if not inv else "bajista",
                 "desc":"Normal" if not inv else "INVERTIDA"},
                {"ind":"US 10Y","val":f"{u10_v}%","tend":"bajando","senal":"neutro",
                 "desc":f"2Y:{u2_v}% 30Y:{u30_v}%"},
                {"ind":"NFCI","val":str(nfci_v),"tend":"estable",
                 "senal":"bajista" if(nfci_v or 0)>0.1 else "alcista",
                 "desc":"NFCI>0 = condiciones mas tensas"},
            ],
            "estadoCurva":{"t10y2y":sp_2_10,"t10y3m":sp_3m_10,
                "senalRecesion":"alta" if inv else "baja",
                "descripcion":"CURVA INVERTIDA" if inv else "Curva normal"}},
        "similitud_historica":sim,"historico_30d":hist30,
        # Sprint 5 E.2: sentimiento es un placeholder PERMANENTE (nunca se ha
        # implementado realmente). Mantenido para no romper consumers del JSON,
        # pero el frontend debería ignorarlo o no mostrarlo prominentemente.
        # Para implementarlo de verdad haría falta GDELT/NewsAPI o similar.
        "sentimiento":{"score":None,"descripcion":"No implementado (placeholder)","placeholder":True},
        "earnings":{"alerta_volatilidad":False,"tickers_72h":[]},
        "derivados":{"precio_qqq":p_qqq},"skew":{},
        "barrida_estructural":{"nivel_barrida":min90_v,"zona_barrida":False},
        "pcr": pcr_d or {"error": "No disponible"},
    }
    return doc

if __name__=="__main__":
    doc=run()
    OUTPUT_FILE.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"\n{'='*60}")
    print(f"  JSON guardado: {OUTPUT_FILE.name}")
    print(f"  QQQ={doc['variables_crudas']['precio_qqq']}  VIX={doc['variables_crudas']['vix']}")
    print(f"  COT fecha={doc['cot'].get('fecha_reporte','?')}  sesgo={doc['cot'].get('sesgo','?')}")
    print(f"  PCR Total={doc['pcr'].get('total','?')}  Equity={doc['pcr'].get('equity','?')}")
    print(f"  FRED 10Y={doc['fred']['us10y']['valor']}%  FF={doc['fred']['fedfunds']['valor']}%")
    print(f"  Risk={doc['risk_compuesto']['valor']}/10  Semaforo={doc['plan_exposicion']['semaforo']}")
    print(f"{'='*60}\n")
