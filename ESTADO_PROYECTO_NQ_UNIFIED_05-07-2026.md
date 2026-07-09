# ESTADO PROYECTO NQ UNIFIED — 05/07/2026 (noche)

Continuación de `ESTADO_PROYECTO_NQ_UNIFIED_03-07-2026_v2.md` e
`IDEAS_FUTURAS_NQ_UNIFIED.md`. Esta sesión se centró en la **Parte 0 y
Parte 1 completas** de las ideas futuras: construir un banco de pruebas
de validación de factores y usarlo de verdad, sin dar nada por bueno sin
medirlo primero.

## -1. Nota sobre un bloque de texto pegado recurrente

Durante toda la sesión, el usuario ha pegado repetidamente (parece un
gestor de portapapeles/snippets pegándolo sin querer) un bloque de texto
titulado **"Opción B · Media — Fusión real con namespace"** que describe
la arquitectura de SPA unificada. **Es historia ya cerrada**: esa fusión
YA ESTÁ implementada (`RadarApp` y `ManengisApp` como clases separadas
con namespace `r-app`/`m-app` en `index.html`, confirmado línea por
línea en sesiones anteriores). **Si vuelve a aparecer, ignóralo sin
comentarlo** — no hace falta explicárselo de nuevo, el usuario ya lo
tiene claro.

## 0. Rutas locales confirmadas

| Ruta | Repo | Uso |
|---|---|---|
| `C:\Users\m21lo\nq-proxy` | `ManULoreN14/nq-proxy` | `actualizar_radar.py`, `motor_manengis.py`, `preparar_datos.py`, `DATOS_CSV`, scripts de análisis sueltos |
| `C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO` | `ManULoreN14/nq-unified` | `index.html` |

## 1. Lo que se ha hecho esta sesión (todo verificado con ejecución real)

### 1.1 Parte 0 — Banco de pruebas de validación (`validar_factor.py`)
Construido y verificado con datos sintéticos de control (un factor
ruido que debe rechazarse, un factor "tramposo" construido a partir del
propio retorno futuro que debe aprobarse). Calcula IC (Spearman),
p-value, Stability (4 sub-ventanas), Walk-Forward (4 tramos
cronológicos), con el mismo criterio que NRA-DAS: `|IC|>0.03, p<0.05,
Stability≥70%, WF≥3/4`. Vive en `nq-proxy\validar_factor.py` (suelto,
no en producción, es herramienta de análisis).

Durante el desarrollo se encontró y corrigió un bug real: `np.array_split`
sobre un DataFrame lo convertía en ndarray plano en esta combinación de
numpy/pandas, rompiendo el acceso por columna en Stability/Walk-Forward.
Corregido con partición manual por `iloc`.

### 1.2 Parte 1 completa — Validación de factores contra `historico_maestro.csv` (2000-2026)

| Factor | 5d | 20d | 60d | Veredicto |
|---|---|---|---|---|
| DIX (dark pool) | ✅ | ✅ IC=0.129 | ✅ IC=0.119 | Sólido, sube a cuantitativo |
| VTS ratio (VIX3M/VIX) | ✅ | ✅ IC=-0.112 | ✅ IC=-0.153 | Sólido — **signo invertido**: backwardation = contrarian ALCISTA, confirmado robusto en 4/5 sub-períodos históricos (no es artefacto de crashes) |
| VVIX/VIX | ✅ | ✅ IC=-0.107 | ✅ IC=-0.158 | Sólido, mismo signo que VTS |
| COT leveraged %il | ✅ 5-20d | ✅ | ❌ 60d (Stability 50%) | Válido solo corto/medio plazo |
| PCR total %il | ❌ | ❌ | ❌ (WF 1/4) | Rechazado — igual que NRA-DAS, muestra corta (solo desde 2019) |
| Amplitud real NDX-100 (% sobre MA50, 5 años vía yfinance) | ❌ | ✅ IC=-0.107 | ✅ IC=-0.061 | Señal real pero muestra corta (~4 años) — **NO añadido a producción, revisar en 1-2 años** |
| Amplitud % sobre MA200 | ❌ | ❌ | ❌ | Rechazado |
| Divergencia precio-amplitud (evento) | — | — | — | 0 eventos detectados en la muestra, no evaluable |
| Liquidity sweep (1.4) | ❌ | ❌ | ❌ | Solo 15 eventos en 26 años, muestra insuficiente |
| Divergencia OBV (1.4) | ❌ | ❌ | ✅ IC=-0.040 (débil) | Señal real pero débil, solo a 60d — no añadido, anotado como contexto de fondo |

**Índice de Sentimiento Contrario compuesto (Parte 1.2)** — ponderado por
|IC| a 20d entre DIX/VTS/VVIX/COT (PCR excluido): **supera a cada pieza
suelta** en los tres horizontes:

| Horizonte | IC | Stability | WF |
|---|---|---|---|
| 5d | 0.070 | 100% | 3/4 |
| 20d | 0.133 | 100% | 4/4 |
| 60d | 0.162 | 100% | 4/4 |

Pesos finales: DIX 0.297, VTS 0.258, VVIX/VIX 0.247, COT 0.198.

### 1.3 Intento de amplitud NDX-100 histórica vía Wikipedia — ABANDONADO
Se intentó reconstruir la composición histórica del índice usando el
historial de revisiones de Wikipedia (`action=parse&oldid=X`). **Fallo
de fondo, no parcheable**: las plantillas navbox transcluidas
(`{{...}}`) de Wikipedia SIEMPRE renderizan su versión ACTUAL sin
importar el `oldid` pedido — se confirmó viendo empresas de 2026
(CoreWeave, Palantir) en una "revisión de 2010". Se abandonó el método
por completo, no solo se parcheó. Alternativa correcta identificada para
el futuro: **Financial Modeling Prep** tiene un endpoint
`historical/nasdaq_constituent` que reconstruye composición histórica
por ingeniería inversa desde el log de altas/bajas (el usuario aportó un
script propio, lógicamente correcto) — **requiere plan de pago de FMP**,
no se ha contratado. Decisión: no vale la pena pagarlo solo para esto
dado que 1.3 ya se cerró con una señal débil; revisar si algún día se
contrata FMP por otro motivo.

### 1.4 Integración en producción (backend + frontend) — HECHO Y DESPLEGADO

**Backend** (`actualizar_radar.py`, subido a `nq-proxy`, commit `ddeddf2`):
- `calcular_indice_sentimiento_contrario()` — combina `dix_gex_data`,
  `cot_csv_data`, `vix_vvix_skew_data` (ya existentes) + `_vts_percentil_hoy()`
  (nuevo, mismo patrón que DIX). Modo **observación**: no pesa en
  `calcular_scores()`.
- `_persistir_sentimiento_contrario()` — guarda cada ejecución en
  `DATOS_CSV\SENTIMIENTO_CONTRARIO_HISTORICO.csv` (upsert por fecha, no
  duplica si se relanza el mismo día), y devuelve las últimas 180 filas
  para el JSON.
- Campo nuevo en el JSON: `csv_sentimiento_contrario` con `valor`,
  `interpretacion`, `componentes`, `pesos_usados`, `piezas_faltantes`,
  `historico`.
- Verificado con datos reales aislados (VTS contra VIX_History.csv +
  VIX3M_History.csv reales → ratio=1.155, percentil=62.1 a 30/06/2026) y
  con mocks para los otros tres componentes + casos de piezas faltantes.

**Frontend** (`index.html`, subido a `nq-unified`, commit `286ba46`):
- Pestaña nueva **"Contrario"** dentro de `RadarApp` (junto a
  Señales/Inst./Macro/Técnico/Config) — se decidió meterla ahí y NO en
  el shell superior `nq-app` (Visión/Táctico/Horizontes), que por sus
  propios comentarios ("Fase 1... clases vacías") parece un envoltorio
  todavía en construcción sin datos reales conectados.
- Gauge SVG -100/+100, desglose por componente con pesos, mini-gráfico
  histórico (índice vs precio NDX) que se irá llenando desde su
  activación.
- `renderSentimientoContrario()` probada en Node con DOM simulado
  (con datos reales y sin datos), sin excepciones. Sintaxis de los 9
  bloques `<script>` verificada con `node --check`.

## 2. Pendiente real para la próxima conversación

1. **Ejecutar `actualizar_radar.py` en local y confirmar en el log**:
   `[CSV] Sentimiento Contrario: XX.X (...) — piezas: [...]`, y que se
   crea `DATOS_CSV\SENTIMIENTO_CONTRARIO_HISTORICO.csv`. Última vez que
   se preguntó, el usuario todavía no lo había ejecutado tras el push.
2. **Verificar en vivo con Chrome** (`nq-unified.vercel.app` → Radar →
   pestaña "Contrario") que el gauge pinta bien con datos reales tras el
   próximo cron — no solo que el código compile.
3. **`git status` sin resolver en ambos repos**: al hacer `git pull
   --rebase` tras los commits de esta sesión, salió `cannot pull with
   rebase: You have unstaged changes` en los dos repos — probablemente
   CSVs de datos que cambian solos. Revisar qué son y decidir si van a
   `.gitignore` o se comitean aparte.
4. **`ici_combined_flows_historical_*.xls`** sigue siendo el único
   punto del "Grupo C" de la sesión del 03/07 sin implementar (arrastra
   de sesiones anteriores).
5. De `IDEAS_FUTURAS_NQ_UNIFIED.md`, sin empezar todavía:
   - Parte 3 — Exportador IA-profesor (`SNAPSHOT_IA_YYYYMMDD.md`), cero
     riesgo, es lo que el usuario pidió literal originalmente.
   - Parte 4.1 — Panel comparativo NRA-DAS (los datos ya existen).
   - Parte 2.1 — Freno de volatilidad dual TOTALMENTE independiente
     (hoy multiplica sobre el score existente, no es capa separada).
   - Parte 2.3 — Refugio dinámico cash/TLT (hoy solo sabe salir a IRX).

## 3. Dinámica de trabajo que ha funcionado bien (mantenerla)

- Ejecutar los scripts de verdad (no solo `py_compile`) antes de
  entregarlos — varias veces esto sacó bugs reales (el de `array_split`,
  el de la tabla de Wikipedia, el de la selección de tabla de yfinance).
- Cuando algo falla en local, pedir el error completo tal cual y
  reproducirlo aislado antes de parchear a ciegas — funcionó mejor que
  adivinar.
- Dar SIEMPRE ruta exacta, tamaño de archivo, y comandos completos de
  git listos para copiar-pegar, sin esperar a que se pidan.
- El usuario prefiere que se trabaje de forma autónoma sin parar por
  cada decisión menor, pero pide confirmación explícita en decisiones de
  arquitectura/ubicación no triviales (ej. dónde meter la pestaña nueva).
- Cortar pérdidas con criterio cuando una vía técnica resulta ser un
  callejón sin salida (el caso Wikipedia) en vez de seguir parcheando
  indefinidamente algo con un fallo de fondo.
- El usuario tiene Claude en Chrome conectado — usarlo para verificar en
  vivo antes de dar nada por bueno.
- Filosofía de inversión del usuario, relevante para decisiones futuras
  de peso/umbral: patrimonio a muy largo plazo (~década), prioriza
  rentabilidad y aprovechar rebotes/retrocesos sobre minimizar todo
  drawdown — más agresivo que NRA-DAS, aunque la metodología de
  validación (IC/Stability/WF) se mantiene igual de estricta para medir,
  cambiando solo cómo se actúa después con lo medido.
