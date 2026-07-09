# ESTADO PROYECTO NQ UNIFIED — 03/07/2026 (sesión tarde, continuación)

> Léelo entero antes de tocar nada. Este documento reemplaza al
> `ESTADO_PROYECTO_NQ_UNIFIED_03-07-2026.md` de la sesión de la mañana —
> todo lo que ahí estaba "pendiente" relacionado con PCR/Max Pain/Grupo C
> ya está resuelto (ver abajo). Arquitectura general (2 repos GitHub, 5
> proyectos Vercel, rutas locales) no ha cambiado, sigue siendo válida.

## 0. CORRECCIÓN IMPORTANTE sobre esta misma sesión

La ruta local real de trabajo de `nq-unified` es **`C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO`**
(confirmado con `git remote -v` → `origin https://github.com/ManULoreN14/nq-unified.git`).
NO `C:\Users\m21lo\nq-unified`. Esa carpeta ya estaba anotada como "no
confirmada" en la sección de rutas locales desde una sesión anterior, y en
esta sesión asumí mal el nombre en vez de comprobarlo, lo que generó una
clonación duplicada innecesaria (`C:\Users\m21lo\nq-unified`, inofensiva
pero de sobra — se puede borrar). **Usar siempre `PROYECTO_NASDAQ_UNIFICADO`
para todo lo relacionado con `index.html`/`nq-unified` a partir de ahora.**

## 1. Qué se ha hecho en esta sesión (todo verificado con datos reales, no conjeturado)

### 1.1 PCR no se actualizaba (Táctico → Datos)
- **Causa real**: `actualizar_manual.bat` solo hacía `git add DATOS_CSV`,
  nunca subía `PCR.txt` (vive en la raíz de `nq-proxy`, no en `DATOS_CSV`).
- **Fix**: `.bat` corregido (`git add DATOS_CSV PCR.txt VIX.txt`) + orden de
  git arreglado (commit ANTES de pull --rebase, no después — si no,
  `preparar_datos.py` deja cambios sin commitear y el pull siempre falla).
- **Estado**: `PCR.txt` ya está en GitHub. Pendiente de ver mañana en la
  web (el cron de esta noche debe recogerlo).

### 1.2 Max Pain / OI vacío (Táctico → Radar 2-5D)
- **Causa real**: el frontend buscaba los strikes en `data.derivados.
  top_call_strikes`, campo que `actualizar_radar.py` dejó de rellenar
  hace tiempo (llega `{}` vacío). Los mismos datos SÍ existen en
  `data.opciones.vencimientos[0]`.
- **Fix**: fallback aditivo en `index.html` (función `aplicarDatosRadar`)
  que construye `oiStrikes` desde `opciones.vencimientos[0]` si
  `derivados` viene vacío.
- **Estado**: ✅ **Verificado en vivo con Chrome** — chip verde, Max
  Pain=725, Resistencia=735, Soporte=660, coincide con el JSON real.
  También corregido el texto del chip (decía "Yahoo" a fuego, ahora usa
  `opciones.fuente` real = "Barchart QQQ CSV local").

### 1.3 Grupo C — los 4 archivos "no usados"
- `cboe_market_stats_*.csv` → **ya se usaba** (era el origen de PCR.txt,
  el problema era el punto 1.1). Además ahora también alimenta
  `PCR_RATIOS_HISTORICO.csv` (percentil real).
- `cboe_ratios_historico.csv` → **corregido un malentendido mío**: NO es
  un export acumulativo de CBOE, lo construía el usuario A MANO (causó
  errores de transcripción reales, ej. "11.0" en vez de "1.0"/"1.1" en
  varias filas). Ahora `preparar_datos.py` lo construye solo, fusionando
  (upsert por fecha) todos los `cboe_market_stats_*.csv` sueltos que haya
  en `DESCARGAS DIARIAS` sobre `DATOS_CSV/PCR_RATIOS_HISTORICO.csv`. El
  usuario YA NO tiene que mantenerlo a mano.
- `cboe_vix_futures_*.csv` + `cboe_futures_settlement_*.csv` → nuevo
  handler `h_vix_futures_curve` (→ `VIX_FUTURES_CURVE.csv`, informativo)
  y `h_vix_txt` (→ `VIX.txt` en raíz, formato que `parsear_vix_ts_txt()`
  YA sabía leer desde antes de esta sesión pero nadie se lo daba nunca).
  Verificado ejecutando literalmente esa función real contra el `VIX.txt`
  generado: `spot=16.57 front=18.10 señal=neutro`.
- `ici_combined_flows_historical_*.xls` → **sigue sin implementar**. Es
  el único de los 4 que queda pendiente de verdad.

### 1.4 Score definitivo (Opción B acordada: NO fusionar Radar+Manengis,
mantener los dos motores y formalizar/repesar cada uno)
- **Radar** (`calcular_scores` en `actualizar_radar.py`):
  - Nueva función `calcular_pcr_percentil_csv()`: percentil histórico real
    del PCR (misma metodología `_csv_percentil` que ya usáis para COT),
    contra `PCR_RATIOS_HISTORICO.csv`. Sustituye los umbrales fijos
    (>1.2/<0.6) en `score_vix_fn` cuando hay ≥60 días de histórico;
    fallback a umbrales fijos si no.
  - `vix_ts` (VX1/VX2 reales) ya llegaba conectado desde antes vía
    `parsear_vix_ts_txt(BASE_DIR)` — solo faltaba que `VIX.txt` existiera
    (punto 1.3). Cero cambios de código necesarios ahí, solo datos.
- **Manengis** (`risk_score` en `motor_manengis.py`), 3 factores nuevos:
  1. **Puente con Radar**: `score_avg` de los 6 horizontes de Radar
     (ya se leía para el histórico, nunca se usaba) ahora suma/resta
     riesgo si es claramente bajista/alcista.
  2. **PCR percentil real** como factor propio (antes Manengis no usaba
     PCR en absoluto para el riesgo).
  3. **VIX Term Structure graduado**: antes backwardation sumaba +2.0 fijo
     siempre; ahora se gradúa por el spread real de futuros VIX (VIX.txt)
     — backwardation fuerte (+3.0), backwardation normal (+2.0), contango
     extremo >25% (+0.5 por complacencia). Fallback al ratio spot
     VIX/VIX3M binario si no hay VIX.txt.
  - Los 3 bloques probados con datos reales (PCR=0.90→p52, VTS spread
    real=+9.3% → sin riesgo extra, correcto).

### 1.5 Gráfico comparativo de rentabilidades
- **Ya no es solo del chat.** Nueva función `calcular_backtest_comparativo()`
  en `actualizar_radar.py`: reconstruye un risk_score simplificado
  (RSI+VIX+VTS+COT percentil) día a día desde 2006 usando
  `historico_maestro.csv` + COT real, mapea a exposición con el MISMO
  semáforo que usa Manengis (<3.5→80%, <5.5→65%, <7.5→45%, resto→20%), y
  calcula 6 curvas: Buy&Hold NDX, Estrategia, 30/70, 50/50, 60/40, 70/30.
- Exporta a `datos_radar.json` bajo la clave `backtest_comparativo`
  (fechas mensuales + métricas CAGR/MaxDD/Sharpe + limitaciones documentadas
  explícitamente dentro del propio JSON).
- **Resultado del backtest** (2006-07 → 2026-06, verificado):
  Buy&Hold CAGR=16.36% MaxDD=-53.71% Sharpe=0.72 · Estrategia
  CAGR=16.52% MaxDD=-35.67% Sharpe=0.91.
- **Limitación honesta**: no reconstruye Fear&Greed / breadth Mag7-NDX100
  / curva 2Y-10Y (sin histórico diario disponible) — el score real de
  producción sería más defensivo en crisis que esta aproximación.
- Panel nuevo en `index.html`, pestaña **Histórico** (arriba del todo,
  antes de la tabla cruzada MANENGIS×Radar), función `pintarBacktestComparativo()`,
  Chart.js, mismo estilo que el resto de la web. Sintaxis verificada con
  `node --check`, NO verificado visualmente en pantalla todavía.

## 2. Archivos entregados esta sesión (los que están en el repo YA, confirmado)

- `nq-proxy/actualizar_manual.bat` ✅ subido y funcionando (verificado con
  salida real de consola, PCR.txt + VIX.txt + PCR_RATIOS_HISTORICO.csv
  llegando a GitHub)
- `nq-proxy/preparar_datos.py` ✅ subido y funcionando (11/11 bloques,
  verificado con salida real)
- `nq-proxy/actualizar_radar.py` ✅ subido (commit e3976ff) — **pendiente
  de que corra el cron esta noche para confirmar que no rompe nada**
- `nq-proxy/motor_manengis.py` ✅ subido (mismo commit) — **misma
  pendiente de confirmación con el cron**
- `nq-unified/index.html` ✅ **subido y VERIFICADO EN VIVO** (commit 2daa55b,
  MD5 idéntico entre lo preparado y lo que hay en GitHub). Capturado con
  Chrome en `nq-unified.vercel.app`: el panel "Backtest comparativo" en
  Histórico se ve y muestra correctamente el aviso *"aún no disponible,
  se generará en la próxima actualización del radar"* — es el estado
  esperado hasta que corra el cron de esta noche con el `actualizar_radar.py`
  nuevo, no un error.

## 3. Pendiente real para la próxima conversación (en orden de prioridad)

1. ~~Confirmar que `index.html` se subió~~ ✅ HECHO Y VERIFICADO EN VIVO.
2. **Verificar en vivo (Chrome) tras el cron de esta noche**:
   - PCR ya aparece relleno en Táctico → Datos (chip verde)
   - `datos_radar.json` tiene la clave `backtest_comparativo` sin error
   - El panel nuevo de la pestaña Histórico se ve bien (gráfico +
     métricas), no solo que compile
   - Que el cron no haya roto nada con los cambios de `risk_score` /
     `calcular_scores` (revisar log de la Action en GitHub si algo falla)
3. **`ici_combined_flows_historical_*.xls`** — único punto del Grupo C
   sin implementar. Ya estaba diseñado en la sección 6.3 del estado
   anterior (`ESTADO_PROYECTO_NQ_UNIFIED_03-07-2026.md` de la mañana),
   sigue siendo válido.
4. Hallazgo menor sin resolver, no urgente: el `git push` final del cron
   (`actualizar_datos.yml`) no lleva `pull --rebase` de seguridad — si
   fallara, lo traga en silencio con `|| echo "Nada que pushear"`. No ha
   pasado, pero si algún día faltan datos sin explicación, es el primer
   sitio a mirar.

## 4. Cosas que el usuario pidió corregir sobre mí mismo (para no repetir)

- No asumir que un CSV es "acumulativo de la fuente" sin comprobarlo —
  `cboe_ratios_historico.csv` lo construía el usuario a mano, me lo
  corrigió con evidencia (los propios archivos) y tenía razón.
- El usuario tiene Claude para Chrome conectado y funcionando — usarlo
  para verificar en vivo antes de dar nada por bueno, no solo mirar el
  código o el JSON por curl.
