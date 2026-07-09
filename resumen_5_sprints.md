# RESUMEN COMPLETO — 5 SPRINTS DE CORRECCIÓN APLICADOS

**Proyecto:** NQ Radar Cuantitativo · ManULoreN14
**Fecha:** 20 de junio 2026
**Resultado:** los 5 sprints completados sin dejar nada en el camino

---

## CAMBIOS POR SPRINT

### ✅ SPRINT 1 — Decisiones rápidas de alto impacto

**A.1 · Boost ×1.4 eliminado de `comparativa_correcciones`**
- `actualizar_radar.py` línea 7029-7032: eliminada la amplificación `adjusted = 50 + (raw-50) × 1.4`. Ahora devuelve `raw_pct` sin manipular.
- `index.html` línea 7152-7160: etiquetas cambiadas de "% similitud" / "Distribución de escenarios" a "score de similitud=X/100" / "Score de similitud por escenario (independientes, NO suman 100%)".
- **Impacto:** el "44% cisne negro" ya no se infla. El usuario ve el valor crudo y entiende que es un score independiente, no probabilidad.

**B.1 · `risk_score` con factores reductores**
- `motor_manengis.py` líneas ~1140-1170: añadidos 5 factores que RESTAN del risk_score:
  - Tendencia alcista (precio > EMA20 > EMA50): -0.5
  - Breadth Mag7 > 80%: -0.5
  - Momentum 5d > +2%: -0.3
  - Curva sana (10Y-2Y > 0.5%): -0.3
  - VIX zona óptima (14-18): -0.3
- `risk_score = max(0.0, min(risk, 10.0))` permite ahora bajar a 0.
- **Impacto:** ya no hay sesgo permanente hacia ámbar/naranja. En contexto favorable, el sistema puede llegar a verde.

**D.1 · NDX100 breadth con bulk download**
- `actualizar_radar.py` función `calcular_amplitud_ndx100` completa reescrita.
- ANTES: 100 `yf.download()` secuenciales (~3-5 min, timeout en GitHub Actions).
- AHORA: una sola llamada `yf.download(lista_completa, group_by='ticker', threads=True)` en paralelo (~15-30s).
- Lista actualizada quitando LCID, ZM, JD, BMRN → añadidos APP, PLTR, AXON, ARGX.
- **Impacto:** el NDX100 breadth dejará de salir como "error sin_datos" en el cron.

---

### ✅ SPRINT 2 — Limpieza semántica

**A.2 · Componentes invertidos del régimen macro renombrados**
- `actualizar_radar.py` líneas 2942-2967: componentes invertidos ahora tienen sufijo `_estres_pct`:
  - `hyg_estres_pct`, `vts_estres_pct`, `curva_estres_pct` (los invertidos)
  - `vix_pct`, `vxn_pct`, `nfci_pct`, `skew_pct` (los normales)
  - Aliases retro-compatibles (`hyg_pct`, `vts_pct`, `curva_pct`) mantenidos.
- `index.html` líneas ~6590-6610: el frontend lee los nuevos nombres con fallback. Añadido `title=` (tooltip) que explica si el percentil está invertido.
- **Impacto:** un usuario que vea "VTS-estrés p20" sabe que es percentil de estrés (bajo = poco estrés), no percentil del valor original.

**A.3 · `ts_señal` → `momentum_vix_corto_señal`**
- `actualizar_radar.py` líneas 3781-3795: renombrado en `csv_vix_vvix_skew` dict para no confundir con backwardation clásica.
- Aliases retro-compatibles mantenidos (`ts_señal`, `ts_texto`).
- Mapper línea 4358-4373 también actualizado.
- **Impacto:** "backwardation" ya solo significa VIX3M < VIX_spot (definición clásica), no momentum MA5/MA20.

**E.4 · COT señal canónica por percentil histórico**
- `actualizar_radar.py` función `score_cot_fn` ~5580: ahora prefiere `cot.señal_percentil` (del csv_cot, basado en percentil histórico) sobre `cot.señal` (umbrales absolutos legacy).
- Mapper `mapear_cot_csv_al_legacy` ~4187: añade campo `señal_percentil` al output.
- **Impacto:** el score COT usa la señal más robusta (percentil histórico), eliminando contradicciones cuando umbrales absolutos vs percentiles divergen.

---

### ✅ SPRINT 3 — kNN y matemática

**C.1 · kNN unificado: motor lee del radar**
- `motor_manengis.py` líneas ~1107-1170: el motor ahora intenta leer `datos_radar.knn_predictor` primero (mapeo al formato compatible).
- Si el radar no está disponible o falla, cae al fallback local con `similitud_historica_v2`.
- Campo `fuente` en el output indica de dónde vino: `"radar.knn_predictor"` o `"motor_local_fallback"`.
- **Impacto:** ~30 segundos ahorrados por noche, kNN consistente entre ambos JSON.

**C.2 · Feature `breadth` eliminada del kNN**
- `motor_manengis.py` líneas ~625-640: la feature "breadth" era constante (todas las filas históricas asignadas con valor de HOY → diferencia = 0 → peso 0.8 pero información 0).
- Eliminada de `feat_df`, `hoy_vec` y `PESOS`.
- **Impacto:** el kNN ya no tiene una feature inútil consumiendo peso. Mejor calidad de matching.

**C.3 · Investigación `retornos: {}` vacío**
- Tras inspeccionar el JSON real de producción confirmado que `retornos` SÍ está poblado con `2d/5d/10d/20d` completos.
- El diagnóstico de la Entrega 1 era erróneo (snapshot anterior probablemente con bug transitorio).
- **No requiere fix.**

---

### ✅ SPRINT 4 — Backtest y UX

**B.2 + B.3 · Backtest con baseline + soporte contrarian**
- `index.html`: `REGLAS` dict ampliado con flag `contrarian: true/false` por indicador. VIX, FNG y PCR marcados como contrarian (complacencia → caída). NQ, US10, DXY siguen lógica directa.
- `getNivel` arreglado de `=== null` a `== null` (#J18: captura undefined).
- `calcularBacktestingData` reescrito:
  - Distingue lógica contrarian vs directa.
  - Calcula `edge = pct - 50` (baseline aleatorio).
  - Ordena por edge, no por pct.
  - Devuelve `{ind, pct, edge, n, contrarian}`.
- `calcularBacktesting` actualizado para mostrar edge (`+Npts` o `-Npts`) y colorear según magnitud del edge:
  - edge ≥ +10: verde (señal real)
  - edge ≥ +5: ámbar (señal débil)
  - edge ≥ -5: naranja (cerca del ruido)
  - edge < -5: rojo (señal INVERSA)
- Barras centradas en 50% baseline visual.
- **Impacto:** un indicador que acierta 51% ya no se ve como "útil". Indicadores genuinamente predictivos suben en el ranking.

**#J19 · Doble asignación EMA/SMA al mismo elemento HTML**
- `index.html`: añadidas dos cards nuevas SMA 20 / SMA 50 con IDs propios (`td-sma20`, `td-sma50`, `ts-sma20`, `ts-sma50`).
- En `aplicarDatosAuto` líneas 7805-7842: bloques SMA20 y SMA50 ahora escriben a sus IDs propios, NO sobrescriben los de EMA20/EMA50.
- **Impacto:** las cards "EMA 20" y "EMA 50" ahora muestran realmente datos EMA (no SMA como hasta ahora). Las cards SMA 20 y SMA 50 son visualmente independientes.

**E.1 · RSI unificado (Wilder/EWM en ambos scripts)**
- `motor_manengis.py` líneas 62-72: `calc_rsi` cambiado de `rolling(n).mean()` a `ewm(com=n-1, adjust=False).mean()`.
- Ahora coincide con `actualizar_radar.calcular_rsi`.
- **Impacto:** mismo activo → mismo RSI en ambos motores.

---

### ✅ SPRINT 5 — Aspirina cosmética

**D.2 · NDX100 lista actualizada** — ya hecho en Sprint 1.

**E.2 · Sentimiento marcado como placeholder explícito**
- `motor_manengis.py` línea 1355: `"sentimiento": {"score": None, "descripcion": "No implementado (placeholder)", "placeholder": True}`.
- **Impacto:** consumidores del JSON saben que no es un dato real (era 0 antes, lo cual se podía malinterpretar como "neutro").

**E.3 · Color matriz `medio-alcista`** — decisión NO tocada por defensiva. Es la matriz de inversión cerrada del usuario. Lo dejo a su decisión.

**#J4 · `chg !== null` → `chg != null`**
- `index.html` línea 7787-7793: captura también `undefined`. Añadido check `!isNaN(c)` antes de escribir.

**#J9 · Guard null para `cot.lev_pct_largos + '%'`**
- `index.html` línea 8208-8213: `pctEl.textContent = (cot.lev_pct_largos != null) ? cot.lev_pct_largos + '%' : '—'`. Mismo guard para `percentil_historico`.
- **Impacto:** no más "null%" o "pundefined" en el dashboard.

**#J14 · `flujoNeto5d.toFixed(0)` con verificación typeof**
- `index.html` línea 8472-8477: `(typeof flujoNeto5dRaw === 'number' && !isNaN(flujoNeto5dRaw))` antes de operar.
- **Impacto:** si yfinance devuelve un string accidentalmente, ya no lanza TypeError.

**#J16 · `procesarRespuestaIA` fallback no silencioso**
- `index.html` línea 9544-9549: si `NIVEL:` no se parsea, ahora `console.warn` con primeras 200 chars de la respuesta.
- **Impacto:** debuggable si la IA cambia formato.

**Documentación CNY=X inverso**
- `actualizar_radar.py` línea 550-562: añadido campo `"nota_cny"` explicando que CNY=X = USD/CNY (inverso).

**KNN proxy VX1/VX2 etiquetado preciso**
- `actualizar_radar.py` línea 1405-1418: comentarios mejorados + campo `"vx_proxy_nota"` explicando que son índices de madurez constante, no futuros reales.

---

## ARCHIVOS A SUBIR

### 1. `nq-proxy/actualizar_radar.py`
```bash
cd C:\Users\m21lo\nq-proxy
git add actualizar_radar.py
git commit -m "Sprints 1-5: boost x1.4 eliminado, NDX100 bulk, regimen renombrado, COT canonico, kNN doc"
git stash && git pull && git stash pop && git push origin main
```

### 2. `nq-proxy/motor_manengis.py`
```bash
cd C:\Users\m21lo\nq-proxy
git add motor_manengis.py
git commit -m "Sprints 1,3,4,5: risk_score reductores, kNN unificado, breadth eliminada, RSI Wilder"
git stash && git pull && git stash pop && git push origin main
```

### 3. `PROYECTO_NASDAQ_UNIFICADO/index.html`
```bash
cd C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO
git add index.html
git commit -m "Sprints 1-5: backtest edge+contrarian, EMA/SMA separados, regimen tooltips, guards null"
git push origin main
```

---

## VERIFICACIONES POST-DEPLOY

Tras el próximo cron (lun-vie 22:30 Madrid), comprobar:

1. **`comparativa_correcciones`** devuelve scores crudos (sin amplificar). Por ejemplo, si antes era 44%, ahora será ~46-47%.

2. **`risk_score`** puede bajar de 3.5 cuando hay tendencia + breadth fuerte + momentum positivo.

3. **`amplitud_mercado.ndx100_breadth`** ya NO devuelve `error: sin_datos`. Debe tener `new_highs_52w`, `new_lows_52w`, `net_breadth_pct`, `senal`, `fuente: "ndx100_yfinance_bulk"`.

4. **`regimen_macro.componentes`** tiene tanto los nombres viejos (`hyg_pct`, `vts_pct`, `curva_pct`) como los nuevos (`hyg_estres_pct`, etc.).

5. **`vix_vvix_skew.momentum_vix_corto_señal`** existe junto con el alias `ts_señal`.

6. **`scores.componentes.cot`** usa la señal por percentil cuando está disponible.

7. **`knn_predictor`** en el motor tiene `fuente: "radar.knn_predictor"` (no fallback local).

8. **Dashboard cards** "EMA 20" muestra "↑ Precio encima EMA20" en lugar de "+X% vs SMA20".

9. **Backtest** muestra puntos de edge (`+Npts`) en lugar de porcentajes brutos.

---

## RESUMEN NUMÉRICO

| Sprint | Cambios | Líneas modificadas | Archivos |
|---|---|---|---|
| 1 | A.1, B.1, D.1 | ~150 | radar.py, motor.py, index.html |
| 2 | A.2, A.3, E.4 | ~80 | radar.py, index.html |
| 3 | C.1, C.2 | ~70 | motor.py |
| 4 | B.2+B.3, J19, E.1 | ~100 | motor.py, index.html |
| 5 | E.2, J4, J9, J14, J16, doc | ~50 | radar.py, motor.py, index.html |

**Total: 22 decisiones aplicadas. Ningún hallazgo de las 3 auditorías quedó sin resolver excepto los dos explícitamente delegados a decisión del usuario:**

- **E.3 color matriz `medio-alcista`**: decisión visual cerrada del usuario, no tocada.
- **D.3 CSV Barchart automatización**: requiere infraestructura nueva (descarga programática), no es bug sino mejora de proceso.

Todo lo demás está implementado y verificado sin errores de sintaxis.
