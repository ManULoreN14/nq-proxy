# ENTREGA 2 — AUDITORÍA EXHAUSTIVA DE `actualizar_radar.py`
## ~80 funciones auditadas · 23 hallazgos · 5 bugs corregidos en esta sesión

---

## RESUMEN EJECUTIVO

| Tipo | Cantidad |
|---|---|
| 🔴 Bugs críticos | 4 |
| 🟠 Problemas de lógica | 8 |
| 🟡 Mejoras recomendadas | 6 |
| ⚠️ Notas de diseño | 5 |
| ✅ Correctos | ~55 funciones |

**Corregidos en esta sesión: 5 bugs (los 4 críticos + 1 typo).**

---

## 🔴 BUGS CRÍTICOS — CORREGIDOS

### BUG #1 — Score técnico con huecos en RSI (línea 5428)
**Antes:** RSI de 35, 40, 65, 67 no daban señal (huecos lógicos)
**Después:** rango RSI cubierto completamente sin huecos
```python
if   rsi >= 70:        s -= 1     # sobrecomprado contrarian
elif rsi >= 65:        s += 0.5   # zona alta momentum
elif rsi >  45:        s += 2     # zona alcista saludable
elif rsi >  30:        s -= 1     # zona bajista (antes faltaba)
else:                   s += 1     # sobrevendido contrarian
```
**Impacto:** todos los días con RSI entre 30-45 o 65-70 ahora producen señal en lugar de 0.

### BUG #2 — Score macro: `elif vix > 30` INALCANZABLE (línea 5461)
**Antes:**
```python
if vix < 16:    s += 1.5
elif vix > 25:  s -= 1.5
elif vix > 30:  s -= 3.0   # ← imposible, vix>30 ya cumple vix>25
```
**Después:** orden invertido, ahora `vix > 30` se detecta:
```python
if   vix > 30:  s -= 3.0   # pánico extremo
elif vix > 25:  s -= 1.5   # estrés elevado
elif vix < 16:  s += 1.5   # complacencia
```
**Impacto:** la señal de pánico VIX>30 ahora se aplica. Antes, una crisis con VIX=35 daba score=−1.5 en lugar de −3.0.

### BUG #11 — Max Pain expirado en CSV de Barchart (línea 3901)
**Antes:** seleccionaba el vencimiento **con mayor OI**, sin filtrar fechas pasadas
**Después:** filtra vencimientos `>= hoy` antes de elegir el target. Si todos están expirados, devuelve `None` con log explícito.
**Impacto:** el "Max Pain 650" del vencimiento del 18 de junio (ya cerrado) deja de aparecer en el dashboard. Soluciona el bug visible más grave del inventario.

### BUG #21 — Typo `"favorable_qqqqqq"` (línea 3012)
**Antes:** `señal_oro_real = "favorable_qqqqqq"`
**Después:** `señal_oro_real = "favorable_qqq"`
**Impacto:** si algún consumidor del JSON compara contra `"favorable_qqq"` exacto, ahora coincide.

### BUG régimen macro `RangeIndex` (línea 2772)
**Antes:** `pd.read_csv(HISTORICO_PATH, index_col=0, parse_dates=True)` — en GitHub Actions el índice quedaba como RangeIndex
**Después:** `index_col="fecha"` explícito + fallback `pd.to_datetime()`
**Impacto:** la pestaña Régimen Macro de Visión Global empezará a mostrar datos en lugar de "desconocido".

---

## 🟠 PROBLEMAS DE LÓGICA (no urgentes, recomendados corregir)

### #4 — `score_vix_fn` ignora la prima VIX vs realized vol
La función solo mira `vix_ts.señal` pero no la prima `VIX − RealizedVol20d`. Hoy esa prima es **−13.2** (peligro subestimado, vol realizada > implícita), pero el score VIX no lo refleja. El score actual es +5.0 ignorando esta señal de riesgo.
**Recomendación:** restar puntos al score VIX cuando la prima sea negativa significativa (vol realizada > VIX → riesgo no descontado).

### #6 — `tnx_chg30` evaluado con `if` truthy
Usa `if tnx_chg30 and tnx_chg30 > 0.30` — frágil si `tnx_chg30 == 0.0`. Mejor `is not None`.

### #9 — COT señal con dos lógicas paralelas
`cot.señal` usa umbrales absolutos (25/35/65/75 % largos), `csv_cot.señal` usa percentil histórico. Ambas van al JSON. Pueden contradecirse y confunden al dashboard.
**Recomendación:** elegir una como canónica (preferir la del percentil histórico, más robusta).

### #10 — Trend4w COT sin escalado
`trend_4w = curr.neto − row_4w.neto` se evalúa con umbrales fijos `>5000` / `<-5000`. Pero el neto total puede ser ±100k contratos — un cambio de 5k es marginal.
**Recomendación:** usar `trend4w / open_interest * 100` para tener cambio relativo.

### #14 — Kelly bruto no usa Sharpe
Kelly óptimo continuo es `μ/σ²`. El código usa Kelly discreto (`(p·W − q·L) / W`) que es válido pero subóptimo. Para 5-day returns funciona razonablemente, pero un Kelly Sharpe daría mejor sizing.

### #17 — Proxy China con umbrales hardcoded
`roc_cny < -0.5%` y `roc_soxx > 1.0%` no están calibrados estadísticamente. Para semis con vol diaria ~2%, ROC 20d de 1% es trivial.
**Recomendación:** usar percentiles históricos en lugar de umbrales fijos.

### #19 — `knn_predictor.retornos = {}` vacío
A pesar de tener 50 vecinos válidos, el campo `retornos` se serializa como dict vacío. Probable bug en `_stats_h()` que no se ejecuta. Requiere depuración en producción.

### #20 — Score amplitud combina señales sin pesos uniformes
`score_amp` mezcla `señal_cobre_oro`, `señal_zscore`, `sesgo_estacional`, `factor_exposicion` con pesos arbitrarios. No documenta por qué Cu/Au pesa ±1.5 y `sesgo×0.5`.
**Recomendación:** documentar la matriz de pesos.

---

## 🟡 MEJORAS RECOMENDADAS (mejora cualitativa)

### #5 — Label/color `score_rf` redundante
"Poco atractiva" aparece dos veces (≥25 y <25), solo cambia color. Falta label intermedio.

### #8 — Componentes invertidos en `regimen_macro`
`vts_pct` y `curva_pct` se exponen al dashboard como percentiles **invertidos** (alto=más estrés). El usuario que mire "VTS p20" puede entenderlo al revés. Recomendación: exponer también el percentil no invertido como `vts_pct_raw`.

### #12 — Proxy VX1/VX2 con VIX9D/VIX3M
Etiquetar índices (madurez constante) como futuros (madurez variable) es impreciso. Funciona como aproximación pero puede confundir.

### #13 — Inconsistencia VIX Term Structure
`csv_vix_vvix_skew.ts_señal` usa MA5/MA20 del VIX (momentum); `vixTS.backwardation` usa VIX3M/VIX_spot (estructura clásica). Ambas se etiquetan "backwardation" pero miden cosas distintas.
**Recomendación:** renombrar el del CSV a `momentum_vix_corto_señal`.

### #15 — Estacionalidad sin pesos relativos
Cada regla suma/resta puntos enteros (`+2`, `−1`) sin diferenciar magnitud histórica. Septiembre (peor mes) vale −2, Sell in May vale −1, pero la diferencia estadística entre ambos podría ser mayor.

### #23 — Boost artificial en `comparativa_correcciones`
```python
adjusted = 50 + (raw_pct - 50) * 1.4
```
Amplifica probabilidades hacia los extremos. Una probabilidad real del 46% se reporta como 44%. **No es matemáticamente probabilidad**, es score ajustado. El dashboard lo muestra como % de probabilidad — confunde.
**Recomendación:** o quitar el ×1.4 o etiquetar como "índice de confianza" en lugar de "%".

---

## ⚠️ NOTAS DE DISEÑO (no bugs)

### #3 — NDX100 lista desactualizada (línea 575)
La lista incluye `LCID`, `ZM`, `JD`, `BMRN` que ya no están en el NDX100. No rompe nada (yfinance los descarga igual) pero ensucia la señal. **No urgente** — actualizar cuando se haga limpieza.

### #16 — `CNY=X` es USD/CNY (inverso)
Cuando `CNY=X` baja, el Yuan se fortalece. La interpretación del código es correcta pero no documentada en el JSON. Podría confundir al usuario que vea `roc_cny_20d: -0.3` y piense "Yuan cae".

### #18 — KNN similitud normalizada por día
`mejor_similitud` es relativa al peor candidato del día, no absoluta. No comparable día a día.

### #22 — Donchian 20 == Donchian 50 cuando coinciden
Si el máximo de 50 sesiones es exactamente el de 20 sesiones, las dos señales pueden disparar a la vez. El `elif` lo protege parcialmente.

### Performance: `calcular_amplitud_ndx100` con 100 yf.download secuenciales
Si los 100 tickers no están en `df`, hace 100 requests HTTP en bucle. **Por eso falla en GitHub Actions con timeout.**
**Recomendación arquitectónica:** usar `yf.download(lista_completa, group_by='ticker')` en una sola llamada. Cambio mayor — requiere refactor de la función.

---

## ✅ FUNCIONES AUDITADAS Y CORRECTAS

| Función | Comentario |
|---|---|
| `calcular_ema/sma/rsi/macd/bollinger/atr/obv/stochastico/roc/vol_relativo` | Implementaciones textbook correctas |
| `calcular_tecnicos` | Ensamblado coherente, todas las EMAs en el dict |
| `calcular_vix_ts` | Backwardation bien definida, percentiles correctos |
| `calcular_etf_flows_reales` | Z-score, divergencia precio-flujo, FxGEX — lógica sólida |
| `calcular_opciones_qqq` (Max Pain principal) | Algoritmo textbook correcto |
| `calcular_cot` (parser y cálculo neto) | 4 fuentes con fallback, cálculo correcto |
| `calcular_liquidez` | Zonas de soporte/resistencia, ATR |
| `calcular_macro_fred` (excepto typo) | Liquidez neta, tipos reales, curva — todo correcto |
| `calcular_amplitud_mercado` Kelly | Fórmula clásica, factor exposición coherente |
| `calcular_knn_predictor` (matemática) | Z-score rolling, distancia ponderada, EXCL_TAIL anti-lookahead |
| `calcular_market_regime_matching` (firmas) | Cosino + euclidiana 70/30 razonable |
| `calcular_cta_levels` | Donchian channels correctos |
| `calcular_proxy_china` | ROC + correlación 30d |
| `calcular_señales_derivadas` (excepto label RF) | Ratios y RF score matemáticamente correctos |

---

## CAMBIOS APLICADOS HOY

| Línea | Cambio |
|---|---|
| 2772 | `index_col=0` → `index_col="fecha"` + fallback to_datetime (régimen macro) |
| 3012 | `"favorable_qqqqqq"` → `"favorable_qqq"` (typo) |
| 3901-3940 | Filtro de vencimientos expirados en `leer_qqq_opciones_csv` |
| 5428-5455 | RSI sin huecos en `score_tecnico` |
| 5458-5466 | Orden invertido en `score_macro_fn` |

---

## PRÓXIMOS PASOS RECOMENDADOS

1. **Hacer push** del `actualizar_radar.py` corregido. El próximo cron probará los 5 fixes.
2. **Verificar mañana** que:
   - El Régimen Macro ya muestra valor (no "desconocido")
   - El Max Pain refleja un vencimiento NO expirado
   - El RSI 35-45 / 65-70 contribuye al score
3. **Decisión pendiente del usuario:** ¿quieres que aborde los 🟠 medios en una sesión posterior, o pasamos a la Entrega 3 (`motor_manengis.py`)?
