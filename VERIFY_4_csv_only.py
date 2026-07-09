"""
═══════════════════════════════════════════════════════════════════════════
VERIFY 4 — LECTURA DE CSV, INDEPENDIENTE DEL CALENDARIO DE MERCADO
═══════════════════════════════════════════════════════════════════════════
Las funciones leer_*_csv() de actualizar_radar.py NO dependen de si el
mercado está abierto — solo dependen de que los archivos existan en
DATOS_CSV/. El único motivo por el que no se ejecutan en domingo es que
main() corta la ejecución ANTES de llegar a esa parte (paso A0, calendario).

Este script llama DIRECTAMENTE a esas 4 funciones, sin pasar por main(),
así que funciona CUALQUIER día — incluido hoy. NO modifica datos_radar.json,
NO modifica historico_maestro.csv, NO hace git push. Es de solo lectura.

Uso (desde C:\\Users\\m21lo\\nq-proxy, junto a actualizar_radar.py):
    python VERIFY_4_csv_only.py
═══════════════════════════════════════════════════════════════════════════
"""
import importlib.util
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
script = BASE / "actualizar_radar.py"
if not script.exists():
    print(f"❌ No encuentro actualizar_radar.py en {BASE}")
    print("   Ejecuta este script desde la misma carpeta que actualizar_radar.py")
    sys.exit(1)

print(f"📂 Cargando {script} (solo lectura, sin ejecutar main)...")
spec = importlib.util.spec_from_file_location("ar", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(f"   VERSION = {mod.VERSION}")
print(f"   DATA_CSV_DIR = {mod.DATA_CSV_DIR}")
print()


def linea(ok, txt):
    print(("✅ " if ok else "❌ ") + txt)


# ── 1. DIX / GEX (SqueezeMetrics) ───────────────────────────────────────────
print("═" * 70)
print(" DIX / GEX — SqueezeMetrics (DIX.csv)")
print("═" * 70)
linea(mod.DIX_CSV.exists(), f"DIX_CSV existe: {mod.DIX_CSV}")
dg = mod.leer_dix_gex_csv()
if dg:
    print(f"   fecha={dg.get('fecha')}  dix={dg.get('dix')}%  gex_b={dg.get('gex_b')}B")
    print(f"   dix_percentil={dg.get('dix_percentil')}  gex_percentil={dg.get('gex_percentil')}")
    print(f"   dix_señal={dg.get('dix_señal')}  gex_señal={dg.get('gex_señal')}  gex_regimen={dg.get('gex_regimen')}")
    hist = dg.get('historico_90d', [])
    linea(len(hist) >= 30, f"historico_90d: {len(hist)} días")
    if hist:
        print(f"   primer día: {hist[0]}")
        print(f"   último día: {hist[-1]}")
else:
    linea(False, "leer_dix_gex_csv() devolvió None")

print()

# ── 2. VIX / VVIX / SKEW (CBOE) ─────────────────────────────────────────────
print("═" * 70)
print(" VIX / VVIX / SKEW — CBOE")
print("═" * 70)
linea(mod.VIX_CSV.exists(), f"VIX_CSV existe: {mod.VIX_CSV}")
linea(mod.VVIX_CSV.exists(), f"VVIX_CSV existe: {mod.VVIX_CSV}")
linea(mod.SKEW_CSV.exists(), f"SKEW_CSV existe: {mod.SKEW_CSV}")
vs = mod.leer_vix_vvix_skew_csv()
if vs:
    print(f"   fecha={vs.get('fecha')}  vix={vs.get('vix_spot')}  vvix={vs.get('vvix')}  skew={vs.get('skew')}")
    print(f"   ratio_vvix_vix={vs.get('ratio_vvix_vix')}  vix_percentil={vs.get('vix_percentil')}")
    hist = vs.get('historico_90d', [])
    linea(len(hist) >= 30, f"historico_90d: {len(hist)} días")
    if hist:
        print(f"   último día: {hist[-1]}")
else:
    linea(False, "leer_vix_vvix_skew_csv() devolvió None")

print()

# ── 3. QQQ Opciones (Barchart) ──────────────────────────────────────────────
print("═" * 70)
print(" QQQ Opciones — Barchart (qqq_quotedata.csv)")
print("═" * 70)
linea(mod.QQQ_OPC_CSV.exists(), f"QQQ_OPC_CSV existe: {mod.QQQ_OPC_CSV}")
qq = mod.leer_qqq_opciones_csv()
if qq:
    print(f"   vencimiento={qq.get('vencimiento')}  precio_qqq={qq.get('precio_qqq')}")
    print(f"   max_pain={qq.get('max_pain')}  dist_max_pain_pct={qq.get('dist_max_pain_pct')}")
    print(f"   pcr={qq.get('pcr')}  resistencia_1={qq.get('resistencia_1')}  soporte_1={qq.get('soporte_1')}")
else:
    linea(False, "leer_qqq_opciones_csv() devolvió None")

print()

# ── 4. COT (CFTC) ────────────────────────────────────────────────────────────
print("═" * 70)
print(" COT — CFTC Disaggregated Futures Only (DATOS_CSV/COT/*.txt)")
print("═" * 70)
linea(mod.COT_CSV_DIR.exists(), f"COT_CSV_DIR existe: {mod.COT_CSV_DIR}")
if mod.COT_CSV_DIR.exists():
    txts = list(mod.COT_CSV_DIR.glob("*.txt")) + list(mod.COT_CSV_DIR.glob("*.TXT"))
    linea(len(txts) > 0, f"{len(txts)} archivo(s) .txt encontrados")
    for t in txts:
        print(f"   - {t.name}")
ct = mod.leer_cot_csv()
if ct:
    print(f"   fecha={ct.get('fecha')}  lev_pct_largos={ct.get('lev_pct_largos')}")
    print(f"   percentil_historico={ct.get('percentil_historico')}  señal={ct.get('señal')}")
    hist = ct.get('historico_52s', [])
    linea(len(hist) >= 10, f"historico_52s: {len(hist)} semanas")
    if hist:
        print(f"   último: {hist[-1]}")
    umb = ct.get('umbrales', {})
    print(f"   umbrales: {umb}")
else:
    linea(False, "leer_cot_csv() devolvió None — esperado si DATOS_CSV/COT/ está vacío")

print()
print("═" * 70)
print(" RESUMEN")
print("═" * 70)
print(" DIX/GEX        :", "✅ OK" if dg else "❌ null")
print(" VIX/VVIX/SKEW  :", "✅ OK" if vs else "❌ null")
print(" QQQ Opciones   :", "✅ OK" if qq else "❌ null")
print(" COT            :", "✅ OK" if ct else "❌ null (necesita .txt en DATOS_CSV/COT/)")
print()
print("Si DIX/GEX, VIX/VVIX/SKEW y QQQ Opciones salen ✅ OK con TUS datos reales,")
print("entonces mañana (mercado abierto) el JSON saldrá correcto en esas 3 partes")
print("sin necesidad de cambiar nada más. Solo falta COT si quieres ese bloque.")
