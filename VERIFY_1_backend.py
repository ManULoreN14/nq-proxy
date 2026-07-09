"""
═══════════════════════════════════════════════════════════════════════════
VERIFY 1 — BACKEND
═══════════════════════════════════════════════════════════════════════════
Comprueba que actualizar_radar.py v8.0 genera un datos_radar.json con todas
las claves CSV nuevas correctamente pobladas.

Uso (desde C:\\Users\\m21lo\\PROYECTO_NASDAQ_UNIFICADO):
    python actualizar_radar.py            # genera datos_radar.json
    python VERIFY_1_backend.py            # verifica el JSON

Si todas las líneas terminan en ✅ → backend OK.
═══════════════════════════════════════════════════════════════════════════
"""
import json
import os
import sys
from pathlib import Path

# ── Resolver ruta del JSON ────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
candidatos = [BASE / "datos_radar.json", Path("datos_radar.json")]
ruta = next((p for p in candidatos if p.exists()), None)
if not ruta:
    print("❌ No encuentro datos_radar.json. Ejecuta primero actualizar_radar.py")
    sys.exit(1)

print(f"📂 Leyendo {ruta}")
with open(ruta, encoding="utf-8") as f:
    d = json.load(f)

print(f"🕒 Generado: {d.get('ts', d.get('generado', '?'))}")
print(f"🔖 Versión:  {d.get('version', d.get('VERSION', '?'))}")
print()

# ── Tests ─────────────────────────────────────────────────────────────────
ok = lambda c: "✅" if c else "❌"
totales = []

print("═══ CLAVES NUEVAS V8.0 ═══")
totales.append(("clave csv_activo presente",     'csv_activo' in d))
totales.append(("clave csv_cot presente",        'csv_cot' in d))
totales.append(("clave csv_vix_vvix_skew presente",  'csv_vix_vvix_skew' in d))
totales.append(("clave csv_dix_gex presente",    'csv_dix_gex' in d))
totales.append(("clave csv_qqq_opciones presente",   'csv_qqq_opciones' in d))

print("\n═══ CONTENIDO csv_dix_gex ═══")
dg = d.get('csv_dix_gex')
if dg:
    totales.append(("dg.dix numérico",      isinstance(dg.get('dix'), (int, float))))
    totales.append(("dg.gex_b numérico",    isinstance(dg.get('gex_b'), (int, float))))
    totales.append(("dg.dix_percentil 0-100", 0 <= (dg.get('dix_percentil') or -1) <= 100))
    totales.append(("dg.gex_percentil 0-100", 0 <= (dg.get('gex_percentil') or -1) <= 100))
    totales.append(("dg.historico_90d lista ≥30 días",
                    isinstance(dg.get('historico_90d'), list) and len(dg.get('historico_90d', [])) >= 30))
    if dg.get('historico_90d'):
        item = dg['historico_90d'][-1]
        totales.append(("último item tiene fecha/dix/gex",
                        all(k in item for k in ('fecha', 'dix', 'gex'))))
    print(f"   dix={dg.get('dix')}% · gex_b={dg.get('gex_b')}B · p_dix={dg.get('dix_percentil')} · p_gex={dg.get('gex_percentil')}")
    print(f"   histórico: {len(dg.get('historico_90d', []))} días")
else:
    print("   ⚠️ csv_dix_gex = null (no hay DIX.csv en DATOS_CSV/)")

print("\n═══ CONTENIDO csv_vix_vvix_skew ═══")
vs = d.get('csv_vix_vvix_skew')
if vs:
    totales.append(("vs.vix_spot numérico",   isinstance(vs.get('vix_spot'), (int, float))))
    totales.append(("vs.vvix numérico",       isinstance(vs.get('vvix'), (int, float))))
    totales.append(("vs.ratio_vvix_vix numérico",  isinstance(vs.get('ratio_vvix_vix'), (int, float))))
    totales.append(("vs.vix_percentil 0-100", 0 <= (vs.get('vix_percentil') or -1) <= 100))
    totales.append(("vs.historico_90d lista ≥30",
                    isinstance(vs.get('historico_90d'), list) and len(vs.get('historico_90d', [])) >= 30))
    print(f"   vix={vs.get('vix_spot')} · vvix={vs.get('vvix')} · skew={vs.get('skew')} · ratio={vs.get('ratio_vvix_vix')}")
    print(f"   histórico: {len(vs.get('historico_90d', []))} días")
else:
    print("   ⚠️ csv_vix_vvix_skew = null (no hay VIX_History.csv en DATOS_CSV/)")

print("\n═══ CLAVES LEGACY (deberían SEGUIR funcionando) ═══")
totales.append(("cot.historico_52s lista",
                isinstance(d.get('cot', {}).get('historico_52s'), list)))
totales.append(("opciones.v1.maxPain numérico",
                isinstance(d.get('opciones', {}).get('v1', {}).get('maxPain'), (int, float))))
totales.append(("vixTermStructure.spot numérico",
                isinstance(d.get('vixTermStructure', {}).get('spot'), (int, float))))

# ── Resumen ───────────────────────────────────────────────────────────────
print("\n═══ RESUMEN ═══")
for nombre, cond in totales:
    print(f"  {ok(cond)} {nombre}")

passed = sum(1 for _, c in totales if c)
total = len(totales)
print(f"\n  {passed}/{total} tests pasados")
if passed == total:
    print("\n✅ BACKEND OK — puedes hacer git push y abrir el dashboard")
else:
    print(f"\n⚠️ {total-passed} tests fallaron — revisa los ❌ arriba")
    sys.exit(1)
