# ENTREGA 3 — AUDITORÍA EXHAUSTIVA DE `motor_manengis.py`
## 17 funciones · 17 hallazgos · 3 bugs corregidos en esta sesión

---

## RESUMEN EJECUTIVO

| Tipo | Cantidad |
|---|---|
| 🔴 Bugs críticos | 3 |
| 🟠 Problemas de lógica | 9 |
| 🟡 Mejoras recomendadas | 3 |
| ⚠️ Notas de diseño | 2 |
| ✅ Correctos | ~12 funciones |

**Corregidos en esta sesión: 3 bugs (todos los críticos).**

---

## 🔴 BUGS CRÍTICOS — CORREGIDOS

### BUG #M12 — Integración breadth radar↔manengis BUSCABA CAMPOS INEXISTENTES
**Antes:** El código que añadimos ayer buscaba `breadth_real` o `breadth` directamente en `datos_radar.json`. Pero el radar guarda el breadth en `amplitud_mercado.ndx100_breadth` con campos COMPLETAMENTE DIFERENTES (`new_highs_52w`, `new_lows_52w`, `net_breadth_pct`). **Y mide otra cosa:** New Highs/Lows 52w, no "% sobre EMA50".

Como el código asumía equivalencia conceptual con el Mag7 (que sí mide % sobre EMA), la sustitución habría dado lecturas erróneas si hubiera funcionado.

**Después:** El motor mantiene SIEMPRE el cálculo del Mag7 EMA20/50 como métrica principal de breadth corto plazo. Adicionalmente, **lee la señal NDX100 NH/NL del radar como métrica COMPLEMENTARIA** (no sustituta):
- Si está disponible: se expone en `manengis.ndx100_breadth`
- Si la señal del radar es `bajista_fuerte` → suma 1.0 al risk
- Si es `bajista` → suma 0.5 al risk

Ahora son **dos métricas distintas que se refuerzan**, no una sobrescribiendo a otra.

### BUG #M14 — Score FRED con SIGNO INVERTIDO (línea 1240)
**Antes:**
```python
"score": -1 if sp_2_10 and sp_2_10>0 else 1
```
Esto decía: curva normal (spread>0) → score **−1** (malo); curva invertida (spread<0) → score **+1** (bueno). **Exactamente al revés** de la realidad financiera.

**Después:**
```python
"score": 1 if sp_2_10 and sp_2_10>0 else -1
```
Curva normal = saludable = +1. Curva invertida = recesionaria = −1.

**Impacto:** cualquier consumidor del JSON que usara `manengis.fred.score` estaba leyendo el signo cambiado.

### BUG #M17 — `vts_est` con UMBRALES CONFUSOS de contango
**Antes:**
```python
vts_est = ("backwardation" if vts_back else
           "contango_normal" if vts_ratio<0.85 else "contango_tenso")
```
Esto clasificaba ratio<0.85 como "normal" y ratio≥0.85 como "tenso". **Conceptualmente al revés:**
- ratio = VIX/VIX3M
- ratio normal en mercados calmados: 0.85-0.95
- ratio muy bajo (<0.85): VIX corto plazo MUY por debajo del 3m = curva muy empinada = **calma extrema / complacencia**
- ratio cercano a 1.0: convergencia, posible cambio de régimen
- ratio > 1.0: backwardation (estrés)

**Después:**
```python
if vts_back:
    vts_est = "backwardation"
elif vts_ratio < 0.85:
    vts_est = "contango_profundo"     # curva muy empinada, calma extrema
else:
    vts_est = "contango_normal"        # rango habitual 0.85-1.0
```

**Impacto:** los días con ratio ~0.92 (perfectamente normales) ya no se etiquetan como "tensos".

---

## 🟠 PROBLEMAS DE LÓGICA (no urgentes)

### #M1 — RSI con SMA vs Wilder/EWM (inconsistencia entre scripts)
`motor_manengis.calc_rsi` usa media móvil simple, pero `actualizar_radar.calcular_rsi` usa media exponencial (Wilder). **Para el mismo activo, los dos pueden dar RSI distintos.** No es bug per se pero los dos motores no consensúan.
**Recomendación:** unificar usando Wilder/EWM en ambos.

### #M2 — Umbrales COT 35/65 hardcoded sin percentil histórico
Igual problema que en `actualizar_radar.py` (hallazgo #9 de Entrega 2). Mejor calibrar con percentil de las últimas 52 semanas.

### #M3 — `pct = 50` cuando `(ll+ls) = 0`
Si no hay contratos largos ni cortos en COT, devuelve pct=50 (engañosamente "neutro perfecto"). Mejor `None`.

### #M4 — `pcr_cboe` no verifica antigüedad del último valor
Coge la última fila válida del CSV de CBOE sin importar la fecha. Si el CSV no se actualiza durante días, devuelve dato viejo sin avisar.

### #M6 — `calcular_breadth.divergencia = pct50 < 60`
Umbral arbitrario sin justificación. Para Mag7 (7 tickers), `pct50 < 60` = menos de 4 sobre EMA50. Plausible pero no calibrado contra histórico.

### #M7 — `similitud_historica_v2` Y `calcular_knn_predictor` HACEN LO MISMO
Los dos scripts ejecutan kNN independientemente con la misma lógica. **Duplicación de trabajo.** Ahora que el radar corre primero, el motor podría leer `datos_radar.knn_predictor` en lugar de calcular el suyo. Ahorra ~30s de ejecución cada noche.

### #M8 — `breadth` constante en `similitud_historica_v2` (línea 627)
```python
base["breadth"] = float(breadth_v or 70.0)
```
Asigna el valor de HOY a todas las filas históricas. **La feature "breadth" tiene peso 0.8 pero NO contribuye al cálculo de similitud** porque todos los candidatos tienen el mismo valor.

### #M9 — Fallback breadth = 70 arbitrario
Si el breadth real no se calcula, se asume 70. Sin justificación estadística. Mejor `np.nan`.

### #M10 — `risk_score` solo tiene factores ADITIVOS, ninguno reductivo
Todos los factores suman al riesgo. **No hay forma de que `risk_score = 0`.** El mínimo realista es ~1 punto. El sistema tiende permanentemente hacia "amarillo/naranja".
**Recomendación:** añadir factores que reduzcan riesgo: tendencia alcista clara, breadth >80%, momentum positivo confirmado, etc.

### #M13 — Sentimiento PLACEHOLDER PERMANENTE
`"sentimiento": {"score": 0, "descripcion": "No calculado"}`. El campo aparece en el dashboard pero nunca se ha implementado.

### #M15 — `cot_vix` umbrales mixtos OR confusos
```python
if neto < -20000 or pct < 48:   senal = "alcista"
```
Con `neto=-25000` y `pct=55` (incoherente), clasifica "alcista" por el neto solo. Mejor usar `AND` o priorizar uno explícitamente.

---

## 🟡 MEJORAS RECOMENDADAS

### #M5 — `fear_greed` sin retry/fallback explícito
La API alternative.me puede fallar; un solo intento. Mejor con 2-3 retries.

### #M11 — Umbral breadth divergencia no se ajusta a la fuente
Antes mi código del breadth radar usaba `pct50 < 60` heredado del Mag7 (7 tickers). Pero hoy el breadth radar es independiente (no se sustituye, se complementa), así que este problema queda mitigado. **Nota para futuro:** si algún día el `actualizar_radar.py` calcula "% sobre EMA50 del QQQ100", su umbral de divergencia debería recalibrarse (probablemente `< 50` o usar percentiles).

### #M16 — `_cot_from_zip` solo año actual, sin fallback anterior
En enero, si el ZIP del nuevo año aún no tiene datos, el motor falla. El radar SÍ tiene fallback año-1, el motor no. Replicar.

---

## ⚠️ NOTAS DE DISEÑO (no son bugs)

### Detección de columnas COT robusta con cascada
La función `cot_nq` tiene cascada de 3 candidatos por columna + fallback `_find_col`. Bien.

### Cobertura kNN multivariable con fallback CSV externos
`similitud_historica_v2` carga DIX, VVIX, SKEW desde CSV externos (con fallback a GitHub raw). Buena ingeniería.

---

## ✅ FUNCIONES AUDITADAS Y CORRECTAS

| Función | Comentario |
|---|---|
| `utcnow_str`, `get_hist`, `last_val`, `calc_ema`, `calc_atr` | Limpias y correctas |
| `fred_series` | API REST oficial bien implementada |
| `_cot_from_zip` | Robusta, normaliza nombres de columnas |
| `cot_nq` (excepto umbrales) | Detección de columnas con cascada, cálculos correctos |
| `cot_vix` (excepto OR mixto) | Lógica inversa correctamente documentada |
| `pcr_cboe` | Búsqueda flexible de columnas |
| `fear_greed` | Umbrales coherentes |
| `_cargar_csv_externo` | Cascada local→GitHub raw |
| `similitud_historica_v2` (lógica core) | EXCL_TAIL anti-lookahead, z-score rolling, distancia ponderada — todo correcto |
| `similitud_historica` (wrapper) | Simple delegación |

---

## CAMBIOS APLICADOS HOY

| Línea | Cambio |
|---|---|
| 1006-1015 | `vts_est`: corregida lógica de contango (#M17) |
| 1041-1080 | Reemplazado el "Mag7 fallback" defectuoso por dos métricas complementarias (#M12) |
| 1142-1149 | Añadido factor de riesgo desde ndx100_breadth_signal del radar |
| 1208-1210 | Expuesto `ndx100_breadth` en JSON para dashboard |
| 1250 | Invertido signo de FRED score (#M14) |

---

## DECISIÓN PENDIENTE — Hallazgos serios sin corregir

### #M7 — Duplicación kNN entre radar y motor
Los dos scripts calculan kNN con misma lógica e idénticas features. Cada noche se ejecutan ambos. El motor podría leer el del radar y ahorrar trabajo.
**Pregunta:** ¿quieres que en una sesión futura lo unifique?

### #M8 — Feature `breadth` no aporta nada al kNN
Está como constante en todas las filas. La señal está peso 0.8 pero información 0.
**Pregunta:** ¿quieres que la quitemos del kNN, o que la reconstruyamos con datos históricos reales?

### #M10 — `risk_score` sesgado hacia amarillo/naranja
Solo suma factores, nunca resta. Imposible llegar a verde (<3.5) sin que TODOS los factores sean inactivos simultáneamente.
**Pregunta:** ¿añadimos factores reductores (tendencia alcista, breadth fuerte, momentum positivo)?

---

## PRÓXIMOS PASOS

1. **Push** del `motor_manengis.py` con los 3 fixes
2. **Verificar mañana** que:
   - `manengis.fred.score = 1` (positivo) en lugar de −1
   - `manengis.variables_crudas.vix_ts_estado = "contango_normal"` (ratio típico)
   - `manengis.ndx100_breadth` aparece poblado cuando el radar tenga datos del NDX100
3. **Decisión sobre la Entrega 4** (auditoría JS del dashboard) — los hallazgos serán principalmente de mostrar/no mostrar campos correctos
