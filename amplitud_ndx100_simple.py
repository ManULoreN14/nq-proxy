# -*- coding: utf-8 -*-
"""
amplitud_ndx100_simple.py
==========================
Version simple (sin arqueologia de Wikipedia, que resulto no ser fiable):
usa la composicion ACTUAL del Nasdaq-100 aplicada a los ultimos N años
(por defecto 5). El sesgo de supervivencia en una ventana de 5 años es
pequeño y asumible -- no merece la pena la complejidad de reconstruir
composicion historica para esta cantidad de años.

Archivo SUELTO, independiente de descargar_datos.py.

CAMBIO (backfill MA20): ahora también calcula pct_sobre_ma20 con los
MISMOS datos ya descargados (sin coste extra), y FUSIONA el resultado
con el CSV existente en vez de sobrescribirlo entero -- así rellena
retroactivamente la columna MA20 para todo el histórico ya acumulado,
sin perder nada. actualizar_radar.py seguirá añadiendo el día de hoy en
adelante con su propio cálculo diario; este script es solo para el
backfill puntual del pasado.

REQUISITOS: pip install yfinance pandas lxml

USO:
    python amplitud_ndx100_simple.py
    python amplitud_ndx100_simple.py --anios 5 --salida "C:\ruta\amplitud.csv"
"""
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anios", type=int, default=5)
    ap.add_argument("--salida", default="amplitud_ndx100_simple.csv")
    args = ap.parse_args()

    import pandas as pd
    import yfinance as yf

    print("Obteniendo componentes actuales del Nasdaq-100 (Wikipedia, tabla actual)...")
    import re
    tablas = pd.read_html(
        __import__("io").StringIO(
            __import__("requests").get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "parse", "page": "Nasdaq-100", "prop": "text",
                        "format": "json", "formatversion": 2},
                headers={"User-Agent": "nq-unified-research/1.0 (uso personal)"},
                timeout=20,
            ).json()["parse"]["text"]
        )
    )

    RE_TICKER = re.compile(r"^[A-Z]{1,6}(-[A-Z])?$")

    def tickers_validos(serie):
        vals = serie.dropna().astype(str).str.strip().str.replace(".", "-", regex=False)
        return [v for v in vals if RE_TICKER.match(v)]

    candidatas = []
    for t in tablas:
        cols = [str(c).lower() for c in t.columns]
        col_ticker = next((c for c, cl in zip(t.columns, cols) if "ticker" in cl or "symbol" in cl), None)
        if col_ticker is None:
            continue
        validos = tickers_validos(t[col_ticker])
        if len(validos) >= 30:
            candidatas.append((len(validos), sorted(set(validos))))

    if not candidatas:
        raise SystemExit("No se encontro ninguna tabla con pinta de lista de componentes. Revisa manualmente la pagina.")

    # La lista de componentes real del Nasdaq-100 tiene ~100-105 tickers
    # (100 empresas, un par con dos clases de accion). Elegimos la
    # candidata mas cercana a ese rango, no la mas grande -- la mas
    # grande suele ser la tabla de HISTORICO de altas/bajas, que tiene
    # mas filas pero no es la composicion vigente.
    _, tickers = min(candidatas, key=lambda x: abs(x[0] - 102))
    print(f"  OK: {len(tickers)} tickers actuales")

    print(f"Descargando precios de {len(tickers)} tickers ({args.anios} anios)...")
    datos = yf.download(tickers, period=f"{args.anios}y", interval="1d",
                         auto_adjust=True, progress=False, threads=True)["Close"]

    ma20 = datos.rolling(20, min_periods=20).mean()
    ma50 = datos.rolling(50, min_periods=50).mean()
    ma200 = datos.rolling(200, min_periods=200).mean()
    n20 = (datos.notna() & ma20.notna())
    n50 = (datos.notna() & ma50.notna())
    n200 = (datos.notna() & ma200.notna())
    pct20 = ((datos > ma20) & n20).sum(axis=1) / n20.sum(axis=1) * 100
    pct50 = ((datos > ma50) & n50).sum(axis=1) / n50.sum(axis=1) * 100
    pct200 = ((datos > ma200) & n200).sum(axis=1) / n200.sum(axis=1) * 100

    nuevo = pd.DataFrame({
        "fecha": datos.index.strftime("%Y-%m-%d"),
        "pct_sobre_ma20": pct20.round(2).values,
        "pct_sobre_ma50": pct50.round(2).values,
        "pct_sobre_ma200": pct200.round(2).values,
    }).dropna(subset=["pct_sobre_ma50"])

    # ── Fusión con el CSV existente (upsert por fecha) ──────────────────
    # En vez de sobrescribir entero: las fechas que ya estaban se
    # ACTUALIZAN (ahora con MA20 relleno), las que no estaban se AÑADEN,
    # y cualquier fecha antigua fuera de la ventana de --anios que no se
    # haya recalculado esta vez SE CONSERVA tal cual.
    import os
    if os.path.exists(args.salida):
        anterior = pd.read_csv(args.salida, dtype={"fecha": str})
        combinado = pd.concat([anterior, nuevo])
        combinado = combinado.drop_duplicates(subset=["fecha"], keep="last")
        combinado = combinado.sort_values("fecha").reset_index(drop=True)
        n_actualizadas = len(set(anterior["fecha"]) & set(nuevo["fecha"]))
        n_nuevas = len(set(nuevo["fecha"]) - set(anterior["fecha"]))
        print(f"Fusionado con {args.salida}: {n_actualizadas} fechas actualizadas (ahora con MA20), {n_nuevas} fechas nuevas.")
    else:
        combinado = nuevo
        print(f"No existía {args.salida} — se crea desde cero.")

    combinado.to_csv(args.salida, index=False, encoding="utf-8")
    print(f"\nGuardado: {args.salida} ({len(combinado)} filas totales)")
    if len(combinado):
        u = combinado.iloc[-1]
        print(f"Ultima fecha: {u['fecha']}  MA20={u.get('pct_sobre_ma20','--')}%  MA50={u['pct_sobre_ma50']}%  MA200={u['pct_sobre_ma200']}%")

if __name__ == "__main__":
    main()

