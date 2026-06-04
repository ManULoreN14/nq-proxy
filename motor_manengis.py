"""
motor_manengis.py  v2.3
========================
Motor principal NQ Unified.
Genera manengis_tactico.json con datos reales del dia.

Ejecutado por:
  - GitHub Actions cron L-V 20:15 UTC (22:15 Madrid)
  - Localmente: python motor_manengis.py

Dependencias: pip install yfinance requests pandas numpy
"""

import json, datetime, sys, warnings
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
    if s is None or len(s)<n+2: return None
    d = s.diff().dropna()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
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

# ── FRED (CSV con reintentos) ─────────────────────────────────────────────────
# FIX v2.3: timeout 25s + 2 reintentos. El CSV de FRED funciona desde Windows.
# Si falla (p.ej. GitHub Actions), devuelve None y el JSON queda sin ese campo.

def fred_series(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    for intento in range(2):
        try:
            r = requests.get(url, timeout=25,
                             headers={"User-Agent":
                                      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code != 200: continue
            lines = [l.split(",") for l in r.text.strip().split("\n")[1:]
                     if "." in l and len(l.split(","))==2]
            if not lines: return None, None
            curr = float(lines[-1][1])
            prev = float(lines[-2][1]) if len(lines)>=2 else curr
            return round(curr,4), round(prev,4)
        except Exception as e:
            if intento==1: print(f"  ! FRED {sid}: {e}")
    return None, None

# ── COT NQ (CFTC API) ────────────────────────────────────────────────────────
# FIX v2.3: los campos correctos en HistoricalViewOiCSFutonly son NonComm_*
# El JSON de salida sigue usando "leveraged_long/short" para compatibilidad con el frontend.

def cot_nq():
    url = (
        "https://publicreporting.cftc.gov/api/odata/v1/HistoricalViewOiCSFutonly"
        "?$filter=Market_and_Exchange_Names%20eq%20%27NASDAQ%20MINI%20-%20CHICAGO%20MERCANTILE%20EXCHANGE%27"
        "&$orderby=Report_Date_as_YYYY_MM_DD%20desc&$top=2&$format=json"
    )
    for intento in range(2):
        try:
            r = requests.get(url, timeout=20,
                             headers={"User-Agent":"Mozilla/5.0"})
            rows = r.json().get("value",[])
            if not rows: return {"error":"Sin datos CFTC"}
            c = rows[0]; p = rows[1] if len(rows)>1 else rows[0]

            # FIX: campo correcto en este endpoint es NonComm_Positions_*
            ll  = int(c.get("NonComm_Positions_Long_All",  0) or 0)
            ls  = int(c.get("NonComm_Positions_Short_All", 0) or 0)
            ll_p = int(p.get("NonComm_Positions_Long_All", 0) or 0)
            ls_p = int(p.get("NonComm_Positions_Short_All",0) or 0)
            al  = int(c.get("Comm_Positions_Long_All",  0) or 0)
            as_ = int(c.get("Comm_Positions_Short_All", 0) or 0)

            neto      = ll - ls
            neto_prev = ll_p - ls_p
            pct  = round(ll/(ll+ls)*100,1) if (ll+ls)>0 else 50
            sesgo = "bajista" if pct>65 else "alcista" if pct<35 else "neutro"

            return {
                "fecha_reporte":      c.get("Report_Date_as_YYYY_MM_DD",""),
                "leveraged_long":     ll,    # nombre legacy para compatibilidad frontend
                "leveraged_short":    ls,
                "leveraged_net":      neto,
                "leveraged_net_prev": neto_prev,
                "asset_manager_long": al, "asset_manager_short": as_,
                "asset_manager_net":  al-as_,
                "pct_largo": pct, "sesgo": sesgo,
                "descripcion": (
                    f"Non-Commercial {'corto' if neto<0 else 'largo'} "
                    f"neto {abs(neto):,} contratos en NQ. "
                    f"Sesgo: {sesgo.upper()}."
                )
            }
        except Exception as e:
            if intento==1: print(f"  ! COT NQ: {e}")
    return {"error":"No disponible"}

# ── COT VIX (CFTC API) ───────────────────────────────────────────────────────

def cot_vix():
    url = (
        "https://publicreporting.cftc.gov/api/odata/v1/HistoricalViewOiCSFutonly"
        "?$filter=CFTC_Contract_Market_Code%20eq%20%271170E1%27"
        "&$orderby=Report_Date_as_YYYY_MM_DD%20desc&$top=2&$format=json"
    )
    for intento in range(2):
        try:
            r = requests.get(url, timeout=20,
                             headers={"User-Agent":"Mozilla/5.0"})
            rows = r.json().get("value",[])
            if not rows: return {"error":"Sin datos CFTC VIX"}
            c = rows[0]; p = rows[1] if len(rows)>1 else rows[0]

            nl   = int(c.get("NonComm_Positions_Long_All",  0) or 0)
            ns   = int(c.get("NonComm_Positions_Short_All", 0) or 0)
            nl_p = int(p.get("NonComm_Positions_Long_All",  0) or 0)
            ns_p = int(p.get("NonComm_Positions_Short_All", 0) or 0)

            neto      = nl-ns
            neto_prev = nl_p-ns_p
            pct  = round(nl/(nl+ns)*100,1) if (nl+ns)>0 else 50
            senal = "alcista" if (neto<-20000 or pct<48) else \
                    "bajista" if (neto>20000  or pct>52) else "neutro"

            return {
                "fecha_reporte": c.get("Report_Date_as_YYYY_MM_DD",""),
                "nc_long": nl, "nc_short": ns,
                "neto": neto, "neto_prev": neto_prev,
                "pct_largo": pct, "senal": senal,
                "descripcion": (
                    f"Non-Commercial {'cortos' if neto<0 else 'largos'} "
                    f"netos en VIX: {abs(neto):,} contratos. "
                    f"Senal mercado: {senal.upper()}."
                )
            }
        except Exception as e:
            if intento==1: print(f"  ! COT VIX: {e}")
    return {"error":"No disponible"}

# ── FEAR & GREED ─────────────────────────────────────────────────────────────

def fear_greed():
    # Fuente 1: alternative.me (estable)
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
        print(f"  ! Fear&Greed alternative.me: {e}")
    # Fuente 2: CNN
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        d = r.json()
        score  = round(float(d["fear_and_greed"]["score"]),1)
        rating = d["fear_and_greed"]["rating"]
        estado = ("miedo_extremo" if score<20 else "miedo" if score<40 else
                  "neutro" if score<60 else "codicia" if score<80 else "euforia_extrema")
        return {"score":score,"estado":estado,"rating":rating,"fuente":"cnn"}
    except Exception as e:
        print(f"  ! Fear&Greed CNN: {e}")
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

# ── SIMILITUD HISTORICA (kNN) ─────────────────────────────────────────────────
# FIX v2.3: manejo correcto de timestamps timezone-aware de yfinance

def similitud_historica(rsi_v, vix_v, vix_ch3d, roc5d_v, breadth_v, dist_v):
    try:
        qqq_l = yf.Ticker("QQQ").history(period="max")["Close"]
        vix_l = yf.Ticker("^VIX").history(period="max")["Close"]
        if qqq_l.empty or len(qqq_l)<300:
            raise ValueError("Historico insuficiente")

        df = pd.DataFrame({"qqq":qqq_l,"vix":vix_l}).dropna()

        # FIX: comparacion timezone-aware
        idx_tz = df.index.tz
        cutoff = pd.Timestamp("2014-01-01", tz=idx_tz) if idx_tz else pd.Timestamp("2014-01-01")
        df = df[df.index >= cutoff].copy()

        df["rsi"]      = df["qqq"].ewm(span=14).mean()
        df["roc5d"]    = df["qqq"].pct_change(5)*100
        df["vix_ch3d"] = df["vix"].pct_change(3)*100
        df["max60"]    = df["qqq"].rolling(60).max()
        df["dist_max"] = (df["qqq"]-df["max60"])/df["max60"]*100
        df["breadth"]  = 70.0
        df = df.dropna()

        if len(df)<100: raise ValueError("Pocos datos tras limpieza")

        hoy = np.array([dist_v or 0, vix_v or 15, vix_ch3d or 0,
                        rsi_v or 50, roc5d_v or 0, breadth_v or 70], dtype=float)
        pesos      = np.array([2.0,1.5,1.5,1.0,1.0,1.2])
        hist_feats = df[["dist_max","vix","vix_ch3d","rsi","roc5d","breadth"]].values.astype(float)
        std = hist_feats.std(axis=0); std[std==0]=1.0
        hist_n = hist_feats/std; hoy_n = hoy/std

        diffs = (hist_n-hoy_n)*pesos
        dists = np.sqrt((diffs**2).sum(axis=1))
        max_d = float(dists.max()) if dists.size>0 else 1.0
        if max_d==0: max_d=1.0
        sims = 1.0-dists/max_d

        idx_sorted=np.argsort(-sims); k=50; horizonte=20; vecinos_sel=[]
        for i in idx_sorted:
            if len(vecinos_sel)>=k: break
            fecha_idx=df.index[i]
            if (df.index[-1]-fecha_idx).days < horizonte+5: continue
            fut_end=min(i+horizonte,len(df)-1)
            window=df["qqq"].iloc[i:fut_end+1]
            if len(window)<2: continue
            caida=min(0.0,float(window.min()/window.iloc[0]*100-100))
            cat=("ruido" if caida>-3 else "leve" if caida>-5 else
                 "moderada" if caida>-10 else "fuerte" if caida>-20 else "crash")
            vecinos_sel.append({
                "fecha":fecha_idx.strftime("%Y-%m-%d"),
                "similitud":round(float(sims[i]),4),
                "categoria":cat,"caida_max_20d":round(float(caida),2),
            })

        total_v=len(vecinos_sel)
        descs={"ruido":"Sin caida significativa (<3%)","leve":"Correccion leve (3-5%)",
               "moderada":"Correccion moderada (5-10%)","fuerte":"Correccion fuerte (10-20%)",
               "crash":"Crash o caida severa (>20%)"}
        dist={}
        for cat in descs:
            n_cat=sum(1 for v in vecinos_sel if v["categoria"]==cat)
            dist[cat]={"porcentaje":round(n_cat/total_v*100,1) if total_v else 0,
                       "n":n_cat,"descripcion":descs[cat]}

        mejor_sim=vecinos_sel[0]["similitud"] if vecinos_sel else 0.0
        fiable=mejor_sim>=0.3
        pct_ok=dist["ruido"]["porcentaje"]+dist["leve"]["porcentaje"]
        pct_mal=dist["fuerte"]["porcentaje"]+dist["crash"]["porcentaje"]
        interp=(f"La mayoria ({pct_ok}%) se resolvio sin caidas. Contexto benigno."
                if pct_ok>=80 else
                f"Riesgo elevado: {pct_mal}% de momentos similares precedieron correcciones >10%."
                if pct_mal>=15 else
                "Contexto mixto. Correcciones moderadas posibles.")

        return {
            "version":"1.1","generado":utcnow_str(),
            "fecha_referencia":datetime.date.today().isoformat(),
            "fingerprint_hoy":{
                "dist_pct":round(float(dist_v or 0),2),"rsi":rsi_v or 0,
                "vix":vix_v or 0,"vix_change_3d_pct":round(float(vix_ch3d or 0),2),
                "roc5d":roc5d_v or 0,"breadth_pct":breadth_v or 0,
            },
            "config":{"k_vecinos":k,"horizonte_dias":horizonte,"n_dias_base":len(df),
                      "pesos":{"dist_pct":2.0,"vix":1.5,"vix_change_3d_pct":1.5,
                               "rsi":1.0,"roc5d":1.0,"breadth_pct":1.2},
                      "similitud_minima_fiable":0.3},
            "distribucion":dist,"fiable":fiable,"mejor_similitud":mejor_sim,
            "vecinos_top10":vecinos_sel[:10],"interpretacion":interp,
        }

    except Exception as e:
        print(f"  ! Similitud: {e}")
        if OUTPUT_FILE.exists():
            try:
                old=json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
                sim=old.get("similitud_historica",{})
                sim["generado"]=utcnow_str()
                sim["fingerprint_hoy"]={
                    "dist_pct":round(float(dist_v or 0),2),"rsi":rsi_v or 0,
                    "vix":vix_v or 0,"vix_change_3d_pct":round(float(vix_ch3d or 0),2),
                    "roc5d":roc5d_v or 0,"breadth_pct":breadth_v or 0,
                }
                return sim
            except: pass
        return {"version":"1.1","fiable":False,"generado":utcnow_str(),
                "interpretacion":"Sin datos historicos."}

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def run():
    now=datetime.datetime.now(datetime.timezone.utc)
    today=datetime.date.today().isoformat()
    print(f"\n{'='*60}\n  MOTOR MANENGIS v2.3  --  {now.strftime('%Y-%m-%d %H:%M UTC')}\n{'='*60}\n")

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
        vts_est=("backwardation" if vts_back else
                 "contango_normal" if vts_ratio<0.85 else "contango_tenso")
        vts_desc=f"VIX ({p_vix}) {'>' if vts_back else '<'} VIX3M ({p_v3m}): {vts_est}"
    if vix is not None and len(vix)>=4:
        vn=float(vix.iloc[-1]); v3d=float(vix.iloc[-4])
        vix_ch3d=round((vn-v3d)/v3d*100,2) if v3d else None
    print(f"  {vts_est} | spread={vts_spread} | ch3d={vix_ch3d}%")

    print("COT NQ + VIX (CFTC)...")
    cot_nq_d=cot_nq(); cot_vix_d=cot_vix()
    lev_net=cot_nq_d.get("leveraged_net") if cot_nq_d else None
    cot_sesgo=cot_nq_d.get("sesgo","sin_datos") if cot_nq_d else "sin_datos"
    cot_fecha=cot_nq_d.get("fecha_reporte","?") if cot_nq_d else "?"
    print(f"  NQ: net={lev_net} sesgo={cot_sesgo} fecha={cot_fecha}")
    print(f"  VIX: {cot_vix_d.get('senal','?') if cot_vix_d else '?'}")

    print("Breadth Mag7...")
    br=calcular_breadth(MAG7)
    br_pct20=br["pct_sobre_ema20"]; br_pct50=br["pct_sobre_ema50"]; br_div=br["divergencia"]
    print(f"  EMA20={br_pct20}%  EMA50={br_pct50}%  div={br_div}")

    print("FRED (CSV con reintentos)...")
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
    fg_score=fg["score"]; fg_est=fg["estado"]
    print(f"  F&G={fg_score} ({fg_est}) fuente={fg.get('fuente')}")

    print("Similitud historica (kNN)...")
    sim=similitud_historica(rsi_v,p_vix,vix_ch3d,roc5d_v,br_pct50,dist_max)
    print(f"  fiable={sim.get('fiable')} | mejor_sim={sim.get('mejor_similitud')}")

    factores=[]; risk=0.0
    if rsi_v:
        if rsi_v>75:   risk+=1.5; factores.append(f"RSI={rsi_v} sobrecompra extrema")
        elif rsi_v>70: risk+=1.0; factores.append(f"RSI={rsi_v} sobrecompra")
    if p_vix:
        if p_vix>28:   risk+=2.0; factores.append(f"VIX={p_vix} zona panico")
        elif p_vix>22: risk+=1.5; factores.append(f"VIX={p_vix} zona alerta")
        elif p_vix<13: risk+=0.5; factores.append(f"VIX={p_vix} complacencia extrema")
    if vts_back: risk+=2.0; factores.append("VIX Term Structure backwardation")
    if inv:      risk+=1.0; factores.append("Curva tipos invertida 10Y-2Y")
    if fg_score and fg_score>80: risk+=1.0; factores.append(f"F&G={fg_score} euforia extrema")
    if cot_sesgo=="bajista": risk+=0.5; factores.append("COT specs muy largos NQ")
    if br_div: risk+=0.5; factores.append("Breadth Mag7 debil vs precio")
    if nfci_v and nfci_v>0.1: risk+=0.5; factores.append(f"NFCI={nfci_v} condiciones tensas")

    risk_score=round(min(risk,10.0),1)
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
    hist30=[e for e in hist30 if e.get("fecha")!=today]+[{
        "fecha":today,"risk_score":risk_score,"fear_greed_score":fg_score,
        "regimen_mercado":regimen,"exposicion_semaforo":semaforo,"exposicion_pct":exp_pct,
        "precio_qqq":p_qqq,"vix":p_vix}]
    hist30.sort(key=lambda e:e.get("fecha",""))

    doc={
        "version":"2.3","generado":utcnow_str(),
        "fuente":"motor_manengis.py / GitHub Actions","modo":"full",
        "variables_crudas":{
            "precio_qqq":p_qqq,"precio_ndx":p_ndx,"vix":p_vix,"rsi":rsi_v,
            "ema20":ema20_v,"ema50":ema50_v,"atr14":atr_v,"roc5d":roc5d_v,"vix3m":p_v3m,
            "vix_ts_ratio":vts_ratio,"vix_ts_backwardation":vts_back,"vix_ts_estado":vts_est,
            "cot_lev_net":lev_net,"cot_sesgo":cot_sesgo,
            "breadth_pct_ema20":br_pct20,"breadth_pct_ema50":br_pct50,"breadth_divergencia":br_div,
            "exposicion_sugerida_pct":exp_pct,"exposicion_semaforo":semaforo,
            "dist_desde_max_pct":dist_max,"fear_greed_score":fg_score,"fear_greed_estado":fg_est,
            "regimen_mercado":regimen,"regimen_confianza":100,"risk_score":risk_score,
            "fedfunds":ff_v,"us2y":u2_v,"us10y":u10_v,"us30y":u30_v,
            "spread_2_10":sp_2_10,"spread_3m_10":sp_3m_10,"curva_invertida":inv,
        },
        "tecnicos":{"precio":p_qqq,"rsi14":rsi_v,"ema20":ema20_v,"ema50":ema50_v,
                    "atr14":atr_v,"roc5d":roc5d_v},
        "vix_term_structure":{"vix":p_vix,"vix3m":p_v3m,"ratio":vts_ratio,
            "spread":vts_spread,"backwardation":vts_back,"estado":vts_est,"descripcion":vts_desc},
        "cot": cot_nq_d or {"error":"No disponible"},
        "cot_vix": cot_vix_d or {"error":"No disponible"},
        "breadth":br,"fear_greed":fg,
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
            "estado":("Exposicion plena / constructiva" if semaforo=="verde" else
                      "Vigilar / reducir leve" if semaforo=="amarillo" else
                      "Reducir significativo" if semaforo=="naranja" else "Modo defensivo"),
            "accion":"Mantener" if semaforo in("verde","amarillo") else "Reducir",
            "dist_desde_max_pct":dist_max,"max_referencia":max60_v,
            "fuente_max":"yfinance (60 sesiones)","motivos":factores,
            "descripcion":(
                f"Exposicion sugerida {exp_pct}%. "
                f"{'Mantener.' if semaforo in('verde','amarillo') else 'Reducir exposicion.'} "
                f"Factores: {', '.join(factores) if factores else 'Sin senales de ajuste.'}"
            ),
            "barrida_estructural":{"nivel_barrida":min90_v,
                "dist_barrida_pct":round((p_qqq-min90_v)/min90_v*100,2)
                                   if(p_qqq and min90_v) else None,
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
            "score":-1 if sp_2_10 and sp_2_10>0 else 1,
            "estado":"normal" if not inv else "alerta_curva",
            "curva_invertida":inv,
            "curva_descripcion":(
                f"2Y={u2_v}% 10Y={u10_v}% 30Y={u30_v}% | Spread 10Y-2Y={sp_2_10}"
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
                {"ind":"Fed Funds Rate","val":f"{ff_v}%","tend":"estable",
                 "senal":"neutro","desc":"Tipo de intervencion Fed."},
                {"ind":"Curva 10Y-2Y",
                 "val":f"{'+' if(sp_2_10 or 0)>=0 else ''}{sp_2_10}%","tend":"estable",
                 "senal":"alcista" if not inv else "bajista",
                 "desc":"Normal" if not inv else "INVERTIDA - senal recesion"},
                {"ind":"US 10Y Treasury","val":f"{u10_v}%","tend":"bajando",
                 "senal":"neutro","desc":f"2Y: {u2_v}%  30Y: {u30_v}%"},
                {"ind":"NFCI","val":str(nfci_v),"tend":"estable",
                 "senal":"bajista" if(nfci_v or 0)>0.1 else "alcista",
                 "desc":"NFCI > 0 = condiciones mas tensas que la media"},
            ],
            "estadoCurva":{"t10y2y":sp_2_10,"t10y3m":sp_3m_10,
                "senalRecesion":"alta" if inv else "baja",
                "descripcion":"CURVA INVERTIDA" if inv else "Curva normal"}},
        "similitud_historica":sim,"historico_30d":hist30,
        "sentimiento":{"score":0,"descripcion":"No calculado"},
        "earnings":{"alerta_volatilidad":False,"tickers_72h":[]},
        "derivados":{"precio_qqq":p_qqq},"skew":{},
        "barrida_estructural":{"nivel_barrida":min90_v,"zona_barrida":False},
    }
    return doc

if __name__=="__main__":
    doc=run()
    OUTPUT_FILE.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    qqq=doc["variables_crudas"]["precio_qqq"]
    vix=doc["variables_crudas"]["vix"]
    risk=doc["risk_compuesto"]["valor"]
    sem=doc["plan_exposicion"]["semaforo"]
    cot_f=doc["cot"].get("fecha_reporte","?")
    print(f"\n{'='*60}")
    print(f"  JSON guardado: {OUTPUT_FILE.name}")
    print(f"  QQQ={qqq}  VIX={vix}  Risk={risk}/10  Semaforo={sem}")
    print(f"  COT NQ fecha: {cot_f}")
    print(f"{'='*60}\n")
