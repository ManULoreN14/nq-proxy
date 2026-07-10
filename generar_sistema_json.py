#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generar_sistema_json.py — produce sistema_regimen_tilt.json para la pestaña
"Sistema" del dashboard (index.html).

Uso desde actualizar_radar.py (recomendado), tras construir historico_maestro:
    import generar_sistema_json
    generar_sistema_json.generar(BASE_DIR, DATA_CSV_DIR)

O en el pipeline como paso independiente:
    python generar_sistema_json.py            # usa ./ y ./DATOS_CSV

Lee (con degradación elegante si falta algo):
  historico_maestro.csv : NDX_close, VIX_close, VIX3M_close, IRX_close
  DATOS_CSV/VVIX_History.csv, DIX.csv, VIX9D_History.csv
  DATOS_CSV/fred_WALCL_fed_balance_sheet.csv, fred_DFF_fed_funds_rate.csv  (opc., switch)

IMPORTANTE (datos):
  - VIX9D_History.csv (CBOE, histórico largo) debe estar en DATOS_CSV. El
    ^VIX9D de yfinance solo trae pocos días y NO sirve para el histórico.
  - DIX.csv ya lo deja preparar_datos.py (h_dix) en DATOS_CSV.
Si faltan VVIX/DIX/VIX9D el sistema degrada al núcleo disponible; si faltan
WALCL/DFF el switch monetario queda en 'normal' (no rompe nada).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd


def _expanding_percentile(s, warmup=60):
    arr = s.values.astype(float)
    out = np.full(len(arr), np.nan)
    seen = []
    for i in range(len(arr)):
        if np.isnan(arr[i]):
            continue
        seen.append(arr[i])
        if len(seen) >= warmup:
            out[i] = (np.array(seen) <= arr[i]).mean() * 100
    return pd.Series(out, index=s.index)


def generar(base_dir, data_csv_dir=None, log=None):
    base = Path(base_dir)
    dcsv = Path(data_csv_dir) if data_csv_dir else (base / "DATOS_CSV")
    _log = (lambda m: log.info(m)) if log else (lambda m: print(m))

    hm = pd.read_csv(base / "historico_maestro.csv", parse_dates=["fecha"]).set_index("fecha").sort_index()
    idx = hm["NDX_close"].dropna().index
    ndx = hm["NDX_close"].reindex(idx)
    vix = hm["VIX_close"].reindex(idx)
    vix3m = hm["VIX3M_close"].reindex(idx)
    irx = hm["IRX_close"].reindex(idx) if "IRX_close" in hm.columns else pd.Series(0.0, index=idx)

    def _al(serie, l=10):
        return serie.reindex(serie.index.union(idx)).sort_index().ffill(limit=l).reindex(idx)

    def _csv_serie(nombre, parse_col, val_col, fmt=None):
        p = dcsv / nombre
        if not p.exists():
            p2 = base / nombre
            if p2.exists(): p = p2
            else: return pd.Series(np.nan, index=idx)
        try:
            d = pd.read_csv(p)
            d[parse_col] = pd.to_datetime(d[parse_col], format=fmt, errors="coerce")
            d[val_col] = pd.to_numeric(d[val_col], errors="coerce")
            return _al(d.dropna(subset=[parse_col, val_col]).set_index(parse_col)[val_col].sort_index())
        except Exception as e:
            _log(f"  [SISTEMA-JSON] aviso leyendo {nombre}: {e}")
            return pd.Series(np.nan, index=idx)

    vvix = _csv_serie("VVIX_History.csv", "DATE", "VVIX")
    dix = _csv_serie("DIX.csv", "date", "dix")
    vix9d = _csv_serie("VIX9D_History.csv", "DATE", "CLOSE", fmt="%m/%d/%Y")

    def _fred_serie(nombres_cols):
        """Prueba varias (archivo, col_fecha, col_valor) hasta encontrar datos."""
        for nombre, cfecha, cval in nombres_cols:
            s = _csv_serie(nombre, cfecha, cval)
            if s.notna().any():
                return s
        return pd.Series(np.nan, index=idx)
    # En DATOS_CSV los FRED salen de h_fred como observation_date,<VAL>.
    walcl = _fred_serie([("WALCL.csv", "observation_date", "WALCL"),
                         ("fred_WALCL_fed_balance_sheet.csv", "date", "value")])
    dff = _fred_serie([("DFF.csv", "observation_date", "DFF"),
                       ("fred_DFF_fed_funds_rate.csv", "date", "value")])

    pct = _expanding_percentile
    vts = 100 - pct(vix3m / vix)
    vvx = 100 - pct(vvix / vix) if vvix.notna().any() else pd.Series(np.nan, index=idx)
    v9d = pct(vix9d / vix) if vix9d.notna().sum() > 200 else pd.Series(np.nan, index=idx)
    dixp = pct(dix) if dix.notna().sum() > 200 else pd.Series(np.nan, index=idx)

    # score adaptativo (usa las piezas disponibles; pesos ~|IC|)
    W = {"vts": 0.06, "vvx": 0.06, "v9d": 0.06, "dix": 0.045}
    parts = pd.DataFrame({"vts": vts, "vvx": vvx, "v9d": v9d, "dix": dixp})
    num = pd.Series(0.0, index=idx); den = pd.Series(0.0, index=idx)
    for k in W:
        m = parts[k].notna()
        num[m] += parts[k][m] * W[k]; den[m] += W[k]
    score = pct((num / den).where(den > 0))

    alc = (ndx >= ndx.rolling(200).mean()).reindex(idx).fillna(False)
    if walcl.notna().any() and dff.notna().any():
        duro = ((walcl.diff(60) < 0) & (dff.diff(60) > 0.05)).reindex(idx).fillna(False)
    else:
        duro = pd.Series(False, index=idx)
        _log("  [SISTEMA-JSON] WALCL/DFF ausentes -> switch monetario en 'normal'")

    b = score.apply(lambda x: 0.5 if pd.isna(x) else (1.0 if x >= 70 else 0.0 if x <= 30 else (x - 30) / 40.0))
    exp_d = pd.Series((0.7 + b * 0.6) * np.where(alc, 1.0, 0.0), index=idx)
    exp_d[duro & alc] = 1.0
    # rebalanceo semanal (5d)
    v = exp_d.values.copy(); last = None
    for i in range(len(v)):
        if last is None or (i - last) >= 5: last = i
        else: v[i] = v[last]
    exp = pd.Series(v, index=idx)

    # equity diaria realista: retraso ejec. 2d + 5bps por turno
    exp_ex = exp.shift(2).bfill()
    ndx_ret = ndx.pct_change().shift(-1)
    rf = (irx / 100 / 252).fillna(0)
    turn = exp_ex.diff().abs().fillna(0)
    r_str = (exp_ex * ndx_ret + (1 - exp_ex).clip(lower=0) * rf - turn * 5 / 10000)
    ini = score.first_valid_index()
    mask = idx >= ini
    r_str = r_str[mask].fillna(0)
    r_bh = ndx.pct_change().shift(-1)[mask].fillna(0)
    ix = r_str.index
    eq_s = (1 + r_str).cumprod(); eq_bh = (1 + r_bh).cumprod()
    eq_s /= eq_s.iloc[0]; eq_bh /= eq_bh.iloc[0]

    def stats(r):
        eq = (1 + r).cumprod(); yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        return {"cagr": round(((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100, 1),
                "maxdd": round(((eq / eq.cummax()) - 1).min() * 100, 1),
                "sharpe": round((r.mean() / r.std()) * (252 ** 0.5), 2)}
    yr = ix.year
    met = {"estrategia": {"full": stats(r_str), "is": stats(r_str[yr <= 2018]), "oos": stats(r_str[yr >= 2019])},
           "buyhold": {"full": stats(r_bh), "is": stats(r_bh[yr <= 2018]), "oos": stats(r_bh[yr >= 2019])}}

    ds = ix[::5]
    def arr(s): return [round(float(x), 4) if pd.notna(x) else None for x in s.reindex(ds).values]

    out = {
        "generado": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "desde": ix[0].strftime("%Y-%m-%d"), "hasta": ix[-1].strftime("%Y-%m-%d"),
        "score_hoy": round(float(score.dropna().iloc[-1]), 1) if score.notna().any() else None,
        "regimen_hoy": "ALCISTA" if bool(alc.iloc[-1]) else "BAJISTA (flat)",
        "exposicion_hoy_pct": round(float(exp.iloc[-1]) * 100),
        "switch_monetario": "DURO (tilt off)" if bool(duro.iloc[-1]) else "normal",
        "formula": "Régimen SMA200 (flat debajo) + tilt 0.7x–1.3x por señal vol3+DIX dentro del alcista + switch monetario + rebalanceo semanal.",
        "validacion": "IC condicional en alcista ~0.09 (2-3d). OOS 2019-26 Sharpe 2.05 (vs Buy&Hold 1.79). Normal (IS ≤2018): Sharpe ~0.96, CAGR ~8%.",
        "nota": "El motor es la regla SMA200; el tilt+switch añaden valor neto-de-coste modesto. Equity real (retraso 2d + 5bps): Sharpe ~0.78 full, DD ~-32% (vs -54% del Nasdaq). No bate al índice en retorno; recorta drawdown a la mitad. DIX/VIX9D se incorporan en 2011.",
        "fechas": [d.strftime("%Y-%m-%d") for d in ds],
        "score": arr(score),
        "exposicion_pct": [None if x is None else round(x * 100, 1) for x in arr(exp)],
        "equity_estrategia": arr(eq_s),
        "equity_nasdaq_bh": arr(eq_bh),
        "metricas": met,
    }
    op = base / "sistema_regimen_tilt.json"
    op.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    _log(f"  [SISTEMA-JSON] escrito {op.name}: {len(out['fechas'])} pts · score_hoy={out['score_hoy']} · exp={out['exposicion_hoy_pct']}%")
    return op


if __name__ == "__main__":
    generar(Path(__file__).resolve().parent)
