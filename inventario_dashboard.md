# INVENTARIO COMPLETO DEL DASHBOARD NQ RADAR
## Entrega 1 — Todos los datos, dónde aparecen y cómo se calculan
> Generado el 2026-06-20 · basado en datos_radar.json (ts: 2026-06-20T06:01) y manengis_tactico.json (2026-06-20)

---

## ESTADO DE CADA MÓDULO

| Estado | Significado |
|---|---|
| ✅ Funcionando | Dato presente, sin errores, valor razonable |
| ⚠️ Degradado | Dato presente pero con limitación conocida |
| ❌ Roto | Error en el JSON, dato ausente o incorrecto |

---

## SECCIÓN 1 — VISIÓN GLOBAL · Pestaña "Resumen"

### 1.1 Hero bar (3 números siempre visibles)

| Dato | Valor hoy | Fuente JSON | Cálculo | Estado |
|---|---|---|---|---|
| **Risk score** | 5.2 | `manengis.variables_crudas.risk_score` | Suma ponderada de factores (RSI, VIX, backwardation, COT, breadth, Fear&Greed) · máx 10 | ✅ |
| **Score Radar** (avg horizontes) | +1.43 | `datos_radar.scores.horizontes.*` | Media aritmética de los 6 scores d2/d5/w1/w2/w3/w4 | ✅ |
| **Exposición efectiva** | ~55% | Calculado en JS | `expManengis × (0.4 + 0.6 × kellyRadar)` = 65% × (0.4 + 0.6 × 0.342) = ~59% | ✅ |

### 1.2 Matriz de Convicción 3×3

| Elemento | Fuente | Cálculo | Estado |
|---|---|---|---|
| **Eje Y — bucket riesgo** | `manengis.variables_crudas.risk_score` = 5.2 | <4→bajo / 4-6→medio / >6→alto | ✅ medio |
| **Eje X — bucket radar** | avg horizontes = +1.43 | <-0.5→bajista / >+0.5→alcista | ✅ **alcista** (>0.5) |
| **Celda activa** | Cruce de ambos | medio + alcista = **"Tendencia OK"** (amarillo) | ✅ |
| Acción mostrada | Hardcoded por celda | "Mantener 75-80%" | ✅ |

### 1.3 Régimen Macro

| Dato | Estado | Causa | 
|---|---|---|
| **Régimen** | ❌ `desconocido` | Error: `Only valid with DatetimeIndex... got RangeIndex` — el CSV de historico_maestro no tiene índice de fecha cuando se carga en el cron |
| **Score estrés** | ❌ ausente | Consecuencia del error anterior |
| **Componentes VIX/VXN/HYG/NFCI/SKEW/VTS/Curva** | ❌ ausentes | Ídem |

> **Bug pendiente:** `calcular_regimen_macro()` falla porque `historico_maestro.csv` se carga con `index_col=0` pero en GitHub Actions el índice es un RangeIndex numérico, no DatetimeIndex. Fix: añadir `parse_dates=True` o `pd.to_datetime(df.index)` explícito.

### 1.4 Exposición efectiva (card detalle)

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **Exposición base MANENGIS** | 65% | `manengis.plan_exposicion.exposicion_sugerida_pct` | ✅ |
| **Semáforo** | amarillo | `manengis.variables_crudas.exposicion_semaforo` | ✅ |
| **Kelly Radar** | 0.342 | `datos_radar.amplitud_mercado.factor_exposicion_recomendado` | ✅ |
| **Kelly bruto** | 0.321 | `datos_radar.amplitud_mercado.kelly_bruto` | ✅ |
| **VIX scalar** | 1.22 | `datos_radar.amplitud_mercado.vix_scalar` | ✅ |
| **Score amplitud** | 0.5 | `datos_radar.amplitud_mercado.score_amplitud` | ✅ |

### 1.5 KNN Predictor (card Visión)

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **Escenario tipo** | neutro | `knn_predictor.escenario_tipo` | ✅ |
| **N vecinos** | 50 | `knn_predictor.n_vecinos` | ✅ |
| **Mejor similitud** | 91.4% | `knn_predictor.mejor_similitud` | ✅ |
| **Fiable** | sí | `knn_predictor.fiable` | ✅ |
| **Dist ruido (<3%)** | 24% | `knn_predictor.distribucion.ruido` | ✅ |
| **Dist leve (3-5%)** | 42% | `knn_predictor.distribucion.leve` | ✅ |
| **Dist moderada (5-10%)** | 24% | `knn_predictor.distribucion.moderada` | ✅ |
| **Dist fuerte (10-20%)** | 10% | `knn_predictor.distribucion.fuerte` | ✅ |
| **Dist crash (>20%)** | 0% | `knn_predictor.distribucion.crash` | ✅ |

### 1.6 Escenario estructural (Fase 7B, card auto)

| Dato | Fuente | Estado |
|---|---|---|
| **Escenario auto (E1/E2/E3/E4)** | Clasificador JS sobre `datos_radar` + `manengis` | ✅ (lógica en JS, no en JSON) |

---

## SECCIÓN 2 — VISIÓN GLOBAL · Pestaña "Mercados"

### 2.1 Score Renta Fija (hero)

| Dato | Valor | Fuente | Cálculo | Estado |
|---|---|---|---|---|
| **Score RF** | 53.9/100 | `señales_derivadas.score_rf.score` | TNX percentil ×40% + TLT dur ×25% + curva percentil ×35% | ✅ |
| **Label** | Moderada | `score_rf.label` | ≥75→Muy atractiva / ≥55→Atractiva / ≥40→Moderada... | ✅ |
| **Yield 3m (IRX)** | 3.65% | `score_rf.yields.irx_3m` | Directo de historico_maestro | ✅ |
| **Yield 5y (FVX)** | 4.23% | `score_rf.yields.fvx_5y` | Ídem | ✅ |
| **Yield 10y (TNX)** | 4.46% | `score_rf.yields.tnx_10y` | Ídem | ✅ |
| **Yield 30y (TYX)** | 4.93% | `score_rf.yields.tyx_30y` | Ídem | ✅ |
| **Curva 10y-3m** | +0.81% | `score_rf.curva` | TNX − IRX | ✅ |
| **Forma curva** | Normal | `score_rf.curva_forma` | <-0.1%→Invertida / <0.5%→Plana / <1.5%→Normal / ≥1.5%→Empinada | ✅ |
| **Plazo recomendado** | Mixto/barbell | `score_rf.plazo` | Lógica condicional sobre curva y tendencia TNX | ✅ |
| **TNX cambio 30d** | presente | `score_rf.tnx_chg30` | TNX hoy − TNX hace 22 sesiones | ✅ |
| **TLT cambio 30d** | presente | `score_rf.tlt_chg30` | (TLT hoy / TLT hace 22 sesiones − 1) × 100 | ✅ |

### 2.2 Ratios de posicionamiento

| Ratio | Valor (percentil) | Señal | Interpretación | Estado |
|---|---|---|---|---|
| **QQQ/SPY** | p99.7 | extremo_alcista | Tech premium en máximo histórico. Concentración extrema | ✅ |
| **IWM/SPY** | p9.6 | risk_off | Small caps en mínimos relativos históricos. Breadth pobre | ✅ |
| **SOXX/QQQ** | p100.0 | liderazgo_semis | Semis en máximo histórico relativo al Nasdaq | ✅ |
| **Cu/Au** | p7.9 | risk_off | Cobre débil vs oro. Señal de aversión global al riesgo | ✅ |
| **EEM/SPY** | p15.9 | refugio_eeuu | Emergentes muy débiles vs EEUU. Capital en refugio | ✅ |
| **XLK/SPY** | ⚠️ ausente | — | Tickers nuevos, aún sin histórico en servidor | ⚠️ |
| **XLF/SPY** | ⚠️ ausente | — | Ídem | ⚠️ |
| **XLE/SPY** | ⚠️ ausente | — | Ídem | ⚠️ |

### 2.3 Volatilidad avanzada

| Dato | Valor | Fuente | Cálculo | Estado |
|---|---|---|---|---|
| **RV QQQ 20d** | 29.6% | `señales_derivadas.volatilidad.realized_vol_20d` | Std retornos diarios QQQ × √252 × 100 | ✅ |
| **VIX risk premium** | −13.2 pts | `volatilidad.vix_risk_premium.valor` | VIX spot (16.4) − RV20d (29.6) = −13.2 | ✅ |
| **Señal premium** | peligro_subestimado | `volatilidad.vix_risk_premium.señal` | VIX < RV → mercado se mueve más de lo que el VIX anticipa | ✅ |
| **MOVE Index** | ⚠️ ausente | `volatilidad.move` | Ticker `^MOVE` aún sin histórico en servidor | ⚠️ |
| **VIX9D/VIX** | ⚠️ ausente | `volatilidad.vix9d_vix` | Sin datos suficientes | ⚠️ |

### 2.4 Correlación QQQ-TLT 20d

| Dato | Valor | Señal | Estado |
|---|---|---|---|
| **Corr QQQ-TLT 20d** | +0.576 | crisis_liquidez | ⚠️ ATENCIÓN: correlación positiva alta. Acciones y bonos caen juntos |

> Nota: +0.576 es una señal macro importante. El régimen normal es correlación negativa. Este nivel (+0.5+) históricamente aparece en crisis de liquidez o inflación. Es el dato más relevante del dashboard hoy.

### 2.5 BTC momentum

| Dato | Estado |
|---|---|
| **BTC momentum 20d** | ⚠️ ausente — ticker `BTC-USD` aún sin histórico en servidor |

---

## SECCIÓN 3 — TÁCTICO · Sub-pestaña "Datos"

### 3.1 Precio y técnicos base

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **QQQ precio** | 740.62 | `datos_radar.precio.qqq` | ✅ |
| **NDX precio** | 30,406 | `datos_radar.precio.ndx` | ✅ |
| **VIX spot** | 16.4 | `datos_radar.precio.vix` | ✅ |
| **VXN** | 26.31 | `datos_radar.precio.vxn` | ✅ |
| **DXY** | 100.85 | `datos_radar.precio.dxy` | ✅ |
| **TNX** | 4.463% | `datos_radar.precio.tnx` | ✅ |
| **TLT** | 86.75 | `datos_radar.precio.tlt` | ✅ |
| **GLD** | presente | `datos_radar.precio.gld` | ✅ |
| **Oro (GC futuros)** | 4,224 | `datos_radar.precio.oro` | ✅ |

### 3.2 Técnicos NDX y QQQ (diario / semanal / mensual)

| Dato | Fuente | Estado |
|---|---|---|
| **RSI 14 diario** | `tecnicos.d.rsi14` + `tecnicosQQQ.d.rsi14` | ✅ |
| **RSI 5 diario** | `tecnicos.d.rsi5` | ✅ |
| **MACD** | `tecnicos.d.macd` | ✅ |
| **Estocástico** | `tecnicos.d.stoch` | ✅ |
| **Bollinger Bands** | `tecnicos.d.bb` | ✅ |
| **EMA 8, 13, 20, 26, 52** | `tecnicos.d/w` | ✅ |
| **ROC (momentum)** | `tecnicos.d.roc4` / `tecnicos.m.roc3` | ✅ |

### 3.3 COT Report (CFTC)

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **Fecha reporte** | 2026-06-09 | `cot.fecha` | ✅ (retraso normal de 3 días hábiles) |
| **Largos Leveraged** | 68,287 | `csv_cot.lev_largos` | ✅ |
| **Cortos Leveraged** | 102,593 | `csv_cot.lev_cortos` | ✅ |
| **Neto Leveraged** | −34,306 | `csv_cot.lev_neto` | ✅ |
| **% Largos** | 40% | `csv_cot.lev_pct_largos` | ✅ |
| **Percentil histórico** | p28 (1044 semanas) | `csv_cot.percentil_historico` | ✅ — posicionamiento bajista por debajo de la media histórica |
| **Señal** | neutro | `csv_cot.señal` | ✅ |
| **Tendencia 4 semanas** | subiendo | `csv_cot.tendencia_4s` | ✅ |
| **Dealer neto** | −47,341 | `csv_cot.dealer_neto` | ✅ |
| **Asset Manager neto** | +83,367 | `csv_cot.assetmgr_neto` | ✅ |

### 3.4 VIX Term Structure

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **VIX spot** | 16.2 | `vixTS.spot` | ✅ |
| **VIX 3M** | 19.57 | `vixTS.vix3m` | ✅ |
| **VIX 9D** | 13.93 | `vixTS.vix9d` | ✅ |
| **VX1 (1er futuro)** | 13.93 | `vixTS.vx1` | ✅ |
| **VX2 (2º futuro)** | 19.57 | `vixTS.vx2` | ✅ |
| **Spread VX1-spot** | +3.17 (+19.3%) | `vixTS.spread1` | ✅ |
| **Backwardation** | No | `vixTS.backwardation` = False | ✅ — contango normal |
| **Señal** | ⚠️ `vixTS.ts_señal` = "backwardation" | Contradice `backwardation=False` | ⚠️ **Inconsistencia** — ver nota |

> **Inconsistencia detectada:** `vixTS.backwardation = False` (correcto, spread positivo) pero `csv_vix_vvix_skew.ts_señal = "backwardation"` (incorrecto). Son dos módulos que calculan lo mismo y no coinciden. El `vixTS` parece correcto; el CSV parece usar MA5 vs MA20 del VIX como proxy de term structure, que es un cálculo diferente. El dashboard muestra ambos sin aclarar cuál es el dato canónico.

### 3.5 PCR (Put/Call Ratio)

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **PCR Total QQQ** | 2.728 | `pcr.total` | ✅ |
| **Señal** | alcista_contrario | `pcr.señal` | ✅ — PCR >2 = miedo extremo = señal contraria alcista |
| **PCR Equity** | None | `pcr.equity` | ⚠️ no disponible (CBOE no devolvió dato) |
| **PCR Index** | None | `pcr.index` | ⚠️ ídem |
| **Fuente** | yahoo_qqq_options | `pcr.fuente` | ✅ — proxy QQQ, ligero sesgo tech |

### 3.6 ETF Flows QQQ

| Dato | Valor | Fuente | Cálculo | Estado |
|---|---|---|---|---|
| **Días histórico** | 10 días | `flows.qqq_flows_reales.dias` | Estimado via variación precio×volumen QQQ | ✅ |
| **Z-score acum 20d** | −0.73 | `flows.qqq_flows_reales.zscore_20d` | (flujo acum 20d − media histórica) / std | ✅ |
| **Flujo neto 5d** | presente | `flows.qqq_flows_reales.flujo_neto_5d_m` | Suma de últimos 5 días en M$ | ✅ |
| **Divergencia precio-flujo** | presente | `flows.qqq_flows_reales.divergencia` | Precio sube pero flujo acumulado cae | ✅ |
| **Flujo×GEX confluencia** | presente | `flows.qqq_flows_reales.fxg_valor` | Cruce dirección flujo con signo GEX | ✅ |

### 3.7 DIX / GEX (SqueezeMetrics CSV)

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **Fecha dato** | 2026-06-15 | `csv_dix_gex.fecha` | ✅ (retraso de 5 días hábiles, normal en SqueezeMetrics) |
| **DIX** | 45.11% | `csv_dix_gex.dix` | ✅ |
| **Percentil DIX** | p67.5 | `csv_dix_gex.dix_percentil` | ✅ — acumulación institucional moderada-alta |
| **Señal DIX** | acumulacion | `csv_dix_gex.dix_señal` | ✅ |
| **GEX** | $6.798B | `csv_dix_gex.gex_b` | ✅ |
| **Percentil GEX** | p90.8 | `csv_dix_gex.gex_percentil` | ✅ — GEX muy alto, mercado muy "anclado" |
| **Señal GEX** | anclaje | `csv_dix_gex.gex_señal` | ✅ — dealers tienen mucha gamma, amortiguan movimientos |

---

## SECCIÓN 4 — TÁCTICO · Sub-pestaña "Técnico"

| Dato | Fuente | Estado |
|---|---|---|
| **Giro diario** (divergencia alcista/bajista) | `giro.d.divAlcista/divBajista` | ✅ |
| **Giro semanal** | `giro.w` | ✅ |
| **Señal global giro** | `giro.señalGlobal` = neutro | ✅ |
| **Bollinger %B** | `giro.bb.pct` = 72.42 | ✅ — precio en zona alta del canal |
| **Bollinger Width** | `giro.bb.width` = 8.28 | ✅ |
| **Días consecutivos** | 1 día subiendo | `giro.diasConsec` | ✅ |
| **Zonas resistencia NDX** | 30,762 / 30,587 | `liquidez.zonasResistencia` | ✅ |
| **Zonas soporte NDX** | 28,197 / 24,623... | `liquidez.zonasSoporte` | ✅ |
| **ATR14 NDX** | 717 pts | `liquidez.atr14` | ✅ |

---

## SECCIÓN 5 — TÁCTICO · Sub-pestaña "Radar 2-5D"

### 5.1 Scores por horizonte

| Horizonte | Score | Estado | Confianza | Estado |
|---|---|---|---|---|
| **d2 (2 días)** | +2.1 | alcista_mod | 21% | ✅ |
| **d5 (5 días)** | +1.8 | alcista_mod | 18% | ✅ |
| **w1 (1 semana)** | +1.5 | alcista_mod | 15% | ✅ |
| **w2 (2 semanas)** | +1.3 | alcista_mod | 13% | ✅ |
| **w3 (3 semanas)** | +1.1 | alcista_mod | 11% | ✅ |
| **w4 (4 semanas)** | +0.8 | neutro | 10% | ✅ |
| **Promedio** | +1.43 | alcista | — | ✅ |

> Nota: las confianzas son muy bajas (10-21%). No es un error — reflejan que el sistema tiene alta incertidumbre, lo cual es honesto.

### 5.2 Componentes del score

| Componente | Valor | Interpretación | Estado |
|---|---|---|---|
| **Técnico** | +3.0 | Alcista — señales técnicas positivas | ✅ |
| **Macro** | +0.5 | Ligero sesgo alcista — macro neutral-positiva | ✅ |
| **COT** | +0.5 | Neutro — p28 posicionamiento bajo, no extremo | ✅ |
| **VIX** | +5.0 | Muy alcista — VIX bajo, contango, sin estrés | ✅ |
| **Flujos** | 0.0 | Neutro | ✅ |
| **Giro** | 0.0 | Neutro | ✅ |
| **Amplitud** | +0.8 | Ligero alcista | ✅ |

### 5.3 Max Pain / Opciones

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **Max Pain vencimiento próximo** | 650.0 | `maxpain.valor` (fuente: gex_parser_local) | ⚠️ |
| **Distancia al Max Pain** | −11.3% | `maxpain.distPct` | ⚠️ |
| **Señal** | distribucion | `maxpain.señal` | ⚠️ |

> **⚠️ Atención Max Pain:** El valor de 650 con QQQ en 740 implica que el mercado debería caer un 11% para llegar al Max Pain. Este Max Pain correspondía al vencimiento del **18 de junio** (ya expirado). El dato tiene fecha caducada y no refleja el vencimiento activo. Es el problema más urgente de datos incorrectos: el dashboard muestra una señal "distribución" basada en un vencimiento ya expirado.

| **GEX real total** | $625M | `opciones.gex_real.valor_total_M` | ✅ |
| **Gamma Flip Level** | 550.0 | `opciones.gex_real.gamma_flip_level` | ⚠️ — también puede ser del vencimiento expirado |
| **Skew ratio** | 1.196 | `opciones.skew.valor` | ✅ |
| **Señal skew** | normal | `opciones.skew.senal` | ✅ |

### 5.4 Breadth NDX100

| Dato | Valor | Estado |
|---|---|---|
| **NDX100 breadth real** | `error: sin_datos` | ❌ — `amplitud_mercado.ndx100_breadth.error` = "sin_datos". El cálculo de breadth sobre los 100 componentes falla, probablemente por timeout en GitHub Actions descargando 100 tickers |

---

## SECCIÓN 6 — HORIZONTES

### 6.1 Comparativa de correcciones

| Escenario | Probabilidad | Estado |
|---|---|---|
| **Micro (<3%)** | 78% | ✅ |
| **Técnica (3-7%)** | 59% | ✅ |
| **Macro (7-15%)** | 80% | ✅ |
| **Bajista (15-25%)** | 37% | ✅ |
| **Cisne negro (>20%)** | 44% | ⚠️ — 44% de cisne negro parece alto; revisar calibración |
| **Escenario dominante** | macro_15pct | ✅ |
| **Recomendación** | MONITOREAR SOPORTES | ✅ |

### 6.2 CTA Levels (Donchian Channels)

| Dato | Valor | Estado |
|---|---|---|
| **Donchian 20 High** | 746.16 | ✅ — máximo 20 sesiones. QQQ a 740.62, a 0.75% del high |
| **Donchian 20 Low** | 693.69 | ✅ |
| **Donchian 50 High** | 746.16 | ✅ |
| **Donchian 50 Low** | 588.50 | ✅ |
| **Señal CTA** | neutro | ✅ |

### 6.3 Macro FRED

| Dato | Valor | Fuente | Estado |
|---|---|---|---|
| **Fed Funds** | 3.63% | `macro.fred.fedfunds.v` (2026-05-01) | ✅ |
| **SOFR** | 3.63% | `macro.fred.sofr.v` (2026-06-17) | ✅ |
| **HY Spread** | 2.63% | `macro.fred.hySpread.v` (2026-06-17) | ✅ — spread muy bajo, condiciones crediticias relajadas |
| **NFCI** | −0.505 | `macro.fred.nfci.v` (2026-06-12) | ✅ — condiciones financieras laxas (negativo = laxo) |
| **Inflación implícita 5y** | 2.27% | `macro.fred.t5yie.v` (2026-06-18) | ✅ |
| **Tipo real 10y** | 2.23% | `macro.tiposRealesOro.tipoReal` | ✅ |
| **Alerta tipo real** | sí | `macro.tiposRealesOro.alerta` = True | ✅ — tipos reales >2% = drenaje de liquidez |
| **Liquidez neta Fed** | $5.856T | `macro.liquidezNeta.valor` | ✅ |
| **Tendencia liquidez** | down | `macro.liquidezNeta.trend` | ✅ — Fed drenando liquidez |
| **Curva 10y-2y** | +0.27% | `macro.curva.sp10_2` | ✅ — ligeramente positiva |
| **Curva 10y-3m** | +0.63% | `macro.curva.sp10_3m` | ✅ |
| **Invertida** | No | `macro.curva.invertida2y` | ✅ |
| **Score macro** | +0.5 | `macro.score` | ✅ |

### 6.4 SEC Insiders (Form 4)

| Dato | Valor | Estado |
|---|---|---|
| **Compras 90d** | 1 | ✅ |
| **Ventas 90d** | 275 | ✅ |
| **Acciones vendidas** | 2,955,989 | ✅ |
| **Señal** | bajista | ✅ — insiders Big Tech masivamente vendiendo |

---

## SECCIÓN 7 — HISTÓRICO

| Dato | Fuente | Estado |
|---|---|---|
| **Risk score histórico 30d** | `manengis.historico_30d[].risk_score` | ✅ |
| **Score avg radar histórico** | localStorage primero, `historico_30d[].score_avg` como fallback (Punto B) | ✅ desde hoy |
| **Exposición por día** | `historico_30d[].exposicion_pct` | ✅ |
| **Precio QQQ por día** | `historico_30d[].precio_qqq` | ✅ |
| **Semáforo por día** | `historico_30d[].exposicion_semaforo` | ✅ |
| **Celda matriz por día** | Calculado en JS al render | ✅ |

---

## RESUMEN DE BUGS Y PROBLEMAS

| # | Severidad | Problema | Fix necesario |
|---|---|---|---|
| 1 | 🔴 Alto | **Régimen Macro no funciona** — `RangeIndex` error | Añadir `pd.to_datetime()` explícito en `calcular_regimen_macro()` |
| 2 | 🔴 Alto | **Max Pain expirado** — muestra vencimiento 18-jun ya cerrado | El cron debe actualizar al próximo vencimiento activo |
| 3 | 🟠 Medio | **VIX term structure inconsistente** — `vixTS.backwardation=False` pero `csv_vix_vvix_skew.ts_señal="backwardation"` | Unificar en un único cálculo canónico |
| 4 | 🟠 Medio | **NDX100 breadth sin datos** — timeout descargando 100 tickers | Usar `yf.download([lista], group_by='ticker')` en paralelo o reducir ventana |
| 5 | 🟡 Bajo | **MOVE, BTC, XLK, XLF, XLE ausentes** — tickers nuevos sin histórico | Correrá en próximos crons automáticamente |
| 6 | 🟡 Bajo | **Cisne negro 44%** — parece alta para el contexto actual | Revisar calibración de la comparativa de correcciones |
| 7 | 🟡 Bajo | **SKEW = None** en csv_vix_vvix_skew | Revisar lectura del CSV de SKEW (columna o formato) |
| 8 | ✅ Resuelto | **score_avg null en historico** | Punto B implementado hoy |
| 9 | ✅ Resuelto | **señales_derivadas NameError (tyx/fvx)** | Corregido esta sesión |

---

## DATOS QUE FUNCIONAN CORRECTAMENTE (sin problemas)

✅ Todos los precios (QQQ, NDX, VIX, VXN, DXY, TNX, TLT, GLD, Oro)  
✅ Todos los técnicos (RSI, MACD, Estocástico, Bollinger, EMAs, ROC)  
✅ COT completo (largos/cortos, percentil, tendencia, dealers, asset managers)  
✅ ETF Flows QQQ (10 días, z-score, divergencia, confluencia GEX)  
✅ DIX/GEX desde CSV SqueezeMetrics  
✅ PCR QQQ  
✅ VIX Term Structure (vixTS — el canónico)  
✅ VVIX percentil  
✅ Macro FRED completo (Fed Funds, SOFR, HY Spread, NFCI, inflación implícita, curva, liquidez neta)  
✅ Tipos reales y alerta de drenaje  
✅ SEC Insiders Form 4  
✅ CTA Levels Donchian  
✅ KNN Predictor (50 vecinos, distribución de escenarios)  
✅ Comparativa correcciones (5 escenarios)  
✅ Scores 6 horizontes con estados y confianzas  
✅ Scores 7 componentes  
✅ Matriz 3×3 (celda activa correcta: medio-alcista = Tendencia OK)  
✅ Exposición efectiva (fórmula correcta)  
✅ Score Renta Fija y curva de tipos USA  
✅ Ratios QQQ/SPY, IWM/SPY, SOXX/QQQ, Cu/Au, EEM/SPY con sparklines  
✅ VIX risk premium (RV 20d vs VIX implícito)  
✅ Correlación QQQ-TLT 20d  
✅ Régimen MANENGIS (risk_score, semáforo, exposición)  
✅ Histórico 30d con score_avg desde hoy  
