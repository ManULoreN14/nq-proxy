# ESTADO DEL PROYECTO — NQ Unified / Sistema Cuantitativo Nasdaq-100
**Última actualización:** 2 julio 2026 (fin de sesión de auditoría profunda)
**Propósito de este documento:** que una nueva conversación pueda continuar exactamente donde se dejó, sin tener que re-investigar nada de lo ya descubierto aquí.

---

## 1. QUÉ ES ESTE PROYECTO

Un dashboard cuantitativo personal para tomar decisiones de exposición sobre Nasdaq-100 / QQQ. Combina:
- Datos institucionales (COT/CFTC), volatilidad (VIX/VVIX/SKEW), opciones (GEX/DIX/Max Pain/PCR), macro (Fed, tasas, NFCI), y un motor de radar 2-5 días + un motor táctico ("Manengis").
- El usuario (Manu) no es programador; todo el trabajo de código lo hace Claude. El usuario ejecuta scripts/`.bat` pero no edita código.

---

## 2. ARQUITECTURA — LA PIEZA MÁS IMPORTANTE A NO OLVIDAR

### 2.1 Hay DOS repositorios de GitHub separados (esto causó semanas de confusión)

| Repo | Qué contiene | Rol |
|---|---|---|
| **`ManULoreN14/nq-proxy`** | Backend: `actualizar_radar.py`, `motor_manengis.py`, `DATOS_CSV/`, genera `datos_radar.json` y `manengis_tactico.json` | **Fuente de datos real**. Tiene un cron de GitHub Actions (`actualizar_datos.yml`) que corre automáticamente cada noche. |
| **`ManULoreN14/nq-unified`** | Frontend: `index.html` (el dashboard visual, ~18.800 líneas) | **Solo la interfaz**. NO tiene cron activo. Su propio `datos_radar.json`/`manengis_tactico.json` internos están **abandonados y congelados** (no usar, no confundir). |

**Cómo se conectan:** `index.html` (en `nq-unified`) trae los datos en vivo mediante `fetch()` a:
```
https://raw.githubusercontent.com/ManULoreN14/nq-proxy/main/datos_radar.json
https://raw.githubusercontent.com/ManULoreN14/nq-proxy/main/manengis_tactico.json
```
Confirmado en el código con comentarios como `// Fix C — GitHub Raw como URL real`. **Esto significa que solo hace falta arreglar el backend en `nq-proxy`; el frontend en `nq-unified` lo recoge solo, sin fusionar nada.**

### 2.2 Vercel — 5 proyectos, solo 1 importa para la web real

Todos conectados a la cuenta `manuloren14s-projects`:

| Proyecto Vercel | Repo GitHub conectado | Dominio | ¿Es la web real? |
|---|---|---|---|
| nq-proxy | ManULoreN14/nq-proxy | nq-proxy.vercel.app | No (solo backend, sin frontend relevante) |
| nq-proxy-2wff | ManULoreN14/nq-proxy | nq-proxy-2wff.vercel.app | No |
| nq-proxy-ij59 | ManULoreN14/nq-proxy | nq-proxy-ij59.vercel.app | No |
| nq-multihorizonte | ManULoreN14/nq_multiho... | nq-multihorizonte.vercel.app | No investigado a fondo, probablemente legacy |
| **nq-unified** | **ManULoreN14/nq-unified** | **nq-unified.vercel.app** | **✅ SÍ — esta es la web que usa el usuario a diario** |

Confirmado en Vercel → proyecto `nq-unified` → Settings → Git → "Connected Git Repository: ManULoreN14/nq-unified, Connected May 30".

### 2.3 Rutas locales en el PC del usuario (Windows)

| Ruta local | Qué es |
|---|---|
| `C:\Users\m21lo\nq-proxy` | Carpeta del repo `nq-proxy`. Aquí viven `actualizar_radar.py`, `motor_manengis.py`, `preparar_datos.py`, `actualizar_manual.bat`, `DATOS_CSV\` |
| `C:\Users\m21lo\nq-proxy\DESCARGAS DIARIAS` | Carpeta donde el usuario vuelca CADA DÍA los CSV que descarga a mano de CBOE/CFTC/etc. Única carpeta que el usuario toca. |
| `C:\Users\m21lo\nq-proxy\DATOS_CSV` | Carpeta generada automáticamente por `preparar_datos.py` — el usuario NO la toca a mano, se borra y regenera sola. |
| `C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO` | Mencionada por el usuario como que "solo tiene el index.html" — probablemente es la copia de trabajo local del repo `nq-unified` (no confirmado al 100%, pendiente de verificar en próxima sesión si hace falta). |

---

## 3. RUTINA DIARIA DEL USUARIO (ya funcionando, no tocar)

```
1. Descarga los CSV del día (CBOE, CFTC, FRED, etc.)
2. Los pega en C:\Users\m21lo\nq-proxy\DESCARGAS DIARIAS
3. Doble clic en actualizar_manual.bat
   → internamente ejecuta:
     a) python preparar_datos.py   (traduce DESCARGAS DIARIAS -> DATOS_CSV)
     b) git pull --rebase
     c) git add DATOS_CSV
     d) git commit + git push
4. Esa noche (~22:30 Madrid, L-V), el cron de GitHub Actions en nq-proxy corre:
     actualizar_radar.py → motor_manengis.py → commit datos_radar.json + manengis_tactico.json
5. Vercel (proyecto "nq-unified") sirve index.html, que lee esos JSON en vivo desde nq-proxy.
```

**Regla de oro que el usuario debe seguir:** NUNCA ejecutar `actualizar_radar.py` ni `motor_manengis.py` manualmente en su PC. Ya causó una vez un commit con datos viejos que pisó el trabajo bueno (ver Incidente #1 abajo). Su única tarea es el paso 1-3.

---

## 4. INVENTARIO DE `DATOS_CSV` (generado por `preparar_datos.py`)

| Archivo generado | Origen (carpeta DESCARGAS DIARIAS) | Usado por |
|---|---|---|
| `VIX_History.csv` | mismo nombre | `actualizar_radar.py` |
| `VVIX_History.csv` | mismo nombre | `actualizar_radar.py` |
| `DIX.csv` | `squeezemetrics_dix_*.csv` | `actualizar_radar.py` (DIX/GEX real) |
| `skew-history.csv` + `SKEW_History.csv` | `cboe_skew_*.csv` (formato con preámbulo, se limpia) | ambos motores |
| `qqq_quotedata.csv` | `qqq_options_chain_*.csv` | Max Pain, PCR opciones, GEX |
| `NFCI.csv` | `fred_NFCI_financial_conditions.csv` | condiciones financieras |
| `WALCL.csv` | `fred_WALCL_fed_balance_sheet.csv` | balance Fed |
| `COT/cot_209742_consolidado.txt` | Fusión de `F_TFF_2006_2016.csv` + `FinFut17.csv`...`FinFut25.csv` + `cftc_cot_financial_futures_only_2026.txt`, filtrado por código NASDAQ MINI `209742` | COT (leído con `glob("*.txt")`, nombre no importa) |
| **`PCR.txt`** (en la RAÍZ de `nq-proxy`, NO en DATOS_CSV) | `cboe_market_stats_*.csv`, reformateado a tabulaciones | Put/Call Ratio (Total/Equity/Index/SPX) |

**Archivos que el usuario descarga pero que NADIE usa todavía** (huérfanos, cubiertos por API o sin conectar):
- `cboe_vix_futures_*.csv`, `cboe_futures_settlement_*.csv`, `cboe_ratios_historico.csv`, `indexpcarchive.csv` → cubiertos por API online (Plan A funciona, no se implementó Plan B de fallback a estos CSV)
- `ici_combined_flows_historical_*.xls` → sin conectar, ver sección 6 (pendiente)
- `VIX3M_History.csv`, `VIX9D_History.csv` → vía Yahoo Finance online

---

## 5. INCIDENTES INVESTIGADOS Y RESUELTOS EN ESTA SESIÓN

### Incidente #1 — COT y PCR desactualizados en el dashboard
**Causa raíz real (no era un bug de código):** carrera de commits.
1. Cron nocturno corrió ANTES de que el `DATOS_CSV` bueno llegara al repo.
2. El usuario ejecutó sin querer `actualizar_radar.py` en su PC local (commit `c6003c8`, autor humano no bot), reintroduciendo COT viejo.
3. Se resolvió el conflicto de git con `git merge origin/main -X theirs` + `.gitignore` para excluir `DESCARGAS DIARIAS/` y `preparar_datos.log`.
4. El `DATOS_CSV` bueno (COT hasta 2026-06-23, 1046 semanas, verificado cifra a cifra contra el informe oficial CFTC) quedó como último commit en `main`.
**Estado:** esperando el cron de la noche del 2 julio para confirmar que datos_radar.json se regenera con el COT fresco. **Pendiente de verificar en la próxima sesión.**

### Incidente #2 — Bug `undefined%undefined` en "Plan de Exposición"
**Causa:** `motor_manengis.py` envía `"motivos": factores` como lista de **strings simples**. El frontend esperaba objetos `{delta_pct, texto}`. Al hacer `m.delta_pct` sobre un string, sale `undefined`.
**Arreglado:** función `renderPlanExposicion` en `index.html`, ahora acepta ambos formatos (strings planos o `{delta_pct, texto}`), sin `delta_pct` muestra un bullet simple.
**Desplegado y verificado en vivo:** commit en `nq-unified` (`main`), confirmado con `fetch('/').then(html => html.includes('motivosArr'))` → `true`.

### Incidente #3 — PCR vacío en el dashboard
**Causa:** el código busca `PCR.txt` en la raíz de `nq-proxy` (formato tabulado), pero el traductor nunca lo generaba desde `cboe_market_stats_*.csv` (formato comas).
**Arreglado:** añadido `h_pcr()` a `preparar_datos.py`, probado y verificado carácter a carácter contra el parser real (`parsear_pcr_txt`). Genera `PCR.txt` en la raíz de `nq-proxy` (NO en `DATOS_CSV`).

### Incidente #4 — Max Pain vacío
**Diagnóstico:** el código SÍ tiene lógica de auto-relleno (`if (radar.oiStrikes) {...}`), pero depende del mismo `datos_radar.json` desactualizado del Incidente #1. Debería resolverse solo cuando el COT/PCR se actualicen esta noche. **No confirmado todavía — verificar junto con el Incidente #1.**

### Incidente #5 — Discrepancia entre "Flujo ETF estimado" del dashboard y ETF.com
**Diagnóstico:** NO es un bug. Son dos métricas distintas:
- Dashboard: `flujo_estimado = (close - open) * volumen / 1e6` — una aproximación por precio×volumen, calculada en Python.
- ETF.com: dato real de creación/reembolso de participaciones del fondo QQQ.
**Decisión del usuario:** conservar la estimación como está, y AÑADIR un panel nuevo separado para que el usuario introduzca a mano los datos reales de ETF.com (ver sección 6, pendiente de desplegar).

### Incidente #6 — "Escenario Estructural" ¿manual o automático?
**Diagnóstico:** hay DOS paneles con nombre parecido y comportamiento distinto, NO es un bug:
- Pestaña **Visión** → automático (usa COT+VTS+ETF flows).
- Pestaña **Táctico → Radar 2-5D** → selector manual E1/E2/E3/E4, diseñado a propósito para que el usuario clasifique el régimen de mercado a mano; condiciona los informes de IA.
**Recomendación dada al usuario:** como no domina el tema, guiarse por el panel automático de Visión y de momento ignorar/no tocar el selector manual E1-E4.

### Incidente #7 (documentado, pendiente para más adelante) — COT distinto entre pestañas
En la pestaña **Horizontes → INST.** el COT mostraba `Largos 67.0K / Cortos 95.2K`, mientras que en **Táctico → Radar 2-5D** mostraba `68287 / 102593`. Números parecidos pero no idénticos — sin investigar todavía la causa (¿fuente distinta? ¿redondeo? ¿fecha distinta?). **Queda pendiente, el usuario pidió dejarlo para después explícitamente.**

---

## 6. PENDIENTE — PRÓXIMOS PASOS EXACTOS

### 6.1 Verificación inmediata (primera tarea de la próxima sesión)
Entrar a `nq-unified.vercel.app` → Táctico → Radar 2-5D, y comprobar si el COT ya muestra fecha ≈2026-06-23 (o más reciente) en vez de 2026-06-09. Si sigue en 2026-06-09 después de varias noches de cron, **ahí sí habrá un bug real de código que investigar** (posiblemente en cómo `actualizar_radar.py` lee `COT/*.txt`, aunque ya se verificó que usa `glob("*.txt")` genérico así que debería funcionar).

También comprobar si el Max Pain (Incidente #4) y el PCR (Incidente #3, tras el próximo `actualizar_manual.bat` del usuario) ya aparecen rellenos.

### 6.2 Panel de ETF Flows manual — CÓDIGO YA ESCRITO, pendiente que el usuario lo pegue
El usuario tiene el archivo `index.html` completo (con el panel ya insertado, verificado con diff exhaustivo: 164 líneas añadidas, 0 modificadas, IDs únicos, tags balanceados) para pegar él mismo en `https://github.com/ManULoreN14/nq-unified/edit/main/index.html` (seleccionar todo, borrar, pegar el nuevo, commit). Si en la próxima sesión el usuario dice que ya lo pegó, verificar en vivo con:
```js
fetch('/').then(r=>r.text()).then(html => html.includes('rc-etf-manual'))
```
El panel usa `localStorage` (persistente en su navegador), con entrada individual, entrada masiva (pegar varias líneas `fecha,valor`), tabla, exportar/importar JSON de respaldo, y borrar todo.

### 6.3 Panel de flujos macro (ICI) — DISEÑADO, NO IMPLEMENTADO
El usuario eligió la "Opción 1": usar `ici_combined_flows_historical_*.xls` (datos reales del Investment Company Institute) como un **panel nuevo y separado** de contexto macro — NO como sustituto del flujo QQQ, porque son magnitudes distintas (industria completa de fondos USA, mensual + 4 semanas estimadas, no específico de QQQ).
**Estructura del archivo `.xls`** (hoja única `"Weekly MF & ETF Public Report"`):
- Filas 8-36: flujos MENSUALES (enero 2024 - mayo 2026), columnas: Total LT MF+ETF, Equity(Total/Domestic/World), Hybrid, Bond(Total/Taxable/Municipal), Commodity.
- Filas 39-42: **"Estimated weekly fund flows"**, solo últimas 4 semanas.
**Trabajo pendiente para implementar (no empezado):**
1. Añadir un handler a `preparar_datos.py` que traduzca el `.xls` a un CSV canónico (ej. `ICI_FLOWS.csv`) en `DATOS_CSV`.
2. Modificar `actualizar_radar.py` para leer ese CSV y exponerlo en `datos_radar.json` (nuevo campo, ej. `flujos_macro_ici`).
3. Añadir un panel nuevo en `index.html` (probablemente en Horizontes → Macro) que muestre este dato, dejando claro en el texto que es "flujo agregado de toda la industria de fondos, no específico de QQQ".

### 6.3bis Panel de ETF Flows manual — cómo se usa (aclarado para el usuario)
- El usuario puede ir introduciendo datos de **cualquier fecha pasada**, en cualquier orden, poco a poco (no hace falta rellenar día a día ni en orden cronológico). Cada entrada se guarda independiente por fecha.
- "Exportar" = descarga una copia de seguridad `.json` a su PC (opcional, por si cambia de navegador). "Importar" = recuperar esa copia. Para el uso diario normal NO hace falta usar ninguna de las dos, solo escribir fecha+valor y pulsar "+ Añadir".

### 6.3ter MEJORA PENDIENTE (pedida por el usuario) — Gráfico de correlación QQQ vs ETF Flows reales
Una vez el usuario tenga acumulados suficientes días de datos reales en el panel manual (sección 6.2/6.3bis), construir un **gráfico nuevo** (estilo Chart.js, igual que los ya existentes `etf-chart-barras` / `etf-chart-acum`) que compare:
- Precio de QQQ (línea), contra
- Los flujos REALES introducidos a mano por el usuario (barras), en vez de la estimación por precio×volumen.

Objetivo explícito del usuario: **ver visualmente la correlación** entre el precio de QQQ y los flujos reales de entrada/salida del fondo — un gráfico "real" al lado del gráfico "estimado" que ya existe, para poder comparar ambos visualmente. Requiere leer los datos desde `localStorage` (clave `nq_etf_flows_manual_qqq`) y dibujarlos con la misma librería/estilo que los gráficos existentes en la tarjeta de flujos. No iniciado — pendiente para cuando haya datos suficientes acumulados.



### 6.4 Investigar Incidente #7 (COT Horizontes vs Táctico) — pospuesto a petición del usuario

### 6.5 Auditoría métrica a métrica — en curso, metodología acordada
El usuario quiere seguir verificando, uno por uno, que cada dato del dashboard es correcto y no "engaña en sus decisiones". Metodología que ya funcionó bien: usuario aporta el dato "oficial" de referencia (o Claude lo busca), se compara cifra a cifra contra lo que carga el dashboard, si no cuadra se revisa el código para encontrar la causa exacta (no conjeturar). Ya se hizo con éxito para el COT (Imagen 1 del usuario vs CFTC oficial, coincidencia exacta en 7 campos).
**Próxima métrica a auditar:** a decidir por el usuario al retomar.

---

## 7. LECCIONES TÉCNICAS PARA LA PRÓXIMA SESIÓN (evitar repetir errores)

### 7.1 Sobre Claude para Chrome / automatización de navegador
- Funciona bien para: navegar, hacer capturas, leer JSON con `fetch()` en la consola, inspeccionar GitHub Actions/Vercel.
- **Nada fiable para ediciones grandes** en el editor web de GitHub: el viewport cambia de tamaño entre capturas (a veces 697px, a veces 743px de alto), lo que descuadra cualquier clic por coordenadas fijas. Insertar >100 líneas con la acción "type" puede hacer timeout y dejar contenido a medias o duplicado.
- **Método que SÍ funciona de forma fiable** para encontrar una posición exacta en el editor de GitHub:
  1. Clic en el centro del editor (zona segura, lejos de iconos flotantes tipo Copilot).
  2. `Ctrl+F`, escribir un texto ancla único (evitar caracteres especiales como `·`, usar solo ASCII).
  3. `Enter` (esto SELECCIONA el texto encontrado).
  4. `Escape` (cierra la barra de búsqueda, mantiene el cursor/selección).
  5. Desde ahí, `Home`, `Up`, `Home` (o la combinación de flechas necesaria) para reposicionar con precisión relativa al match, NUNCA con coordenadas de pantalla.
- **Para inserciones grandes (>50 líneas), NO usar el editor web en absoluto.** Mejor: construir el archivo completo localmente con Python/bash (edición determinista, verificable con `diff`), y pedir al usuario que lo pegue él mismo (seleccionar todo + pegar + commit), o buscar un método de git push directo en una sesión futura.
- Cuidado con doble-tap de "Discard/Cancel changes": las coordenadas de esos botones también cambian con el viewport; siempre tomar un screenshot fresco antes de cada clic crítico.

### 7.2 Sobre verificación de datos
- Nunca dar por bueno un dato del dashboard sin comprobar en el código de dónde sale realmente. Varias veces lo que parecía "mismo dato, dos sitios distintos" resultó ser dos métricas con nombre parecido pero fuente distinta (Escenario Estructural, Flujo ETF).
- Cuando algo aparece desactualizado, comprobar primero el **timestamp/fecha de generación** del JSON fuente antes de asumir que el código está roto — casi siempre es un problema de secuencia/timing de cron, no de lógica.

---

## 8. GLOSARIO RÁPIDO DE ARCHIVOS CLAVE

| Archivo | Repo | Qué hace |
|---|---|---|
| `actualizar_radar.py` | nq-proxy | Motor principal: lee `DATOS_CSV`, calcula señales, genera `datos_radar.json` |
| `motor_manengis.py` | nq-proxy | Motor táctico: genera `manengis_tactico.json`, incluye `plan_exposicion` (con el bug de `motivos` ya arreglado en frontend) |
| `preparar_datos.py` | nq-proxy (raíz) | Traductor `DESCARGAS DIARIAS` → `DATOS_CSV` + `PCR.txt`. Ejecutado por `actualizar_manual.bat` |
| `actualizar_manual.bat` | nq-proxy (raíz) | Lanzador único que usa el usuario cada día |
| `actualizar_datos.yml` | nq-proxy/.github/workflows | Cron de GitHub Actions, corre `actualizar_radar.py` + `motor_manengis.py` cada noche |
| `index.html` | nq-unified | El dashboard completo (~18.800 líneas tras el panel nuevo). Lee datos vía `raw.githubusercontent` desde nq-proxy |
| `vercel.json` | ambos repos | Config de despliegue Vercel |

---

## 9. DECISIONES DE ARQUITECTURA PREVIAS (contexto histórico, ya ejecutadas)

### 10.1 "Opción B — Fusión real con namespace" — YA IMPLEMENTADA
En algún momento anterior a esta sesión se decidió fusionar los dos dashboards (Radar y Manengis) en una única SPA con navbar de pestañas superior, en vez de mantenerlos como webs separadas. Fue la opción elegida (de varias evaluadas) por dar "una sola URL, una sola PWA, pestaña Visión global que cruza datos, design tokens compartidos". Coste estimado entonces: 1-2 días de esfuerzo, HTML resultante de ~9.000-10.000 líneas.

**Confirmado que ya está hecha:** el `index.html` actual de `nq-unified` (analizado a fondo en esta sesión) YA tiene exactamente esa estructura: navbar superior con pestañas `NQ / Visión / Táctico / Horizontes / Histórico`, mezclando contenido de ambos motores (Radar + Manengis) en una sola SPA. El archivo ronda las 18.800 líneas (más que la estimación original de 9-10k, probablemente por crecimiento orgánico posterior a la fusión inicial).

**Importante para la próxima sesión:** si en algún momento alguien (el usuario u otra IA) vuelve a plantear "deberíamos fusionar los dos dashboards", la respuesta es que **ya está fusionado** — no reabrir este trabajo. Lo que SÍ sigue separado son los repositorios de GitHub (`nq-proxy` para datos, `nq-unified` para la interfaz ya fusionada), lo cual es correcto y no necesita cambiar (ver sección 2.1).


---

## 10. PARA EMPEZAR LA PRÓXIMA CONVERSACIÓN

Frase sugerida para el usuario al abrir el nuevo chat: *"Continuamos el proyecto NQ Unified, aquí tienes el estado completo"* + adjuntar este archivo. Claude debe leerlo entero antes de hacer cualquier otra cosa, y puede saltar directamente a la sección 6 (Pendiente) para saber por dónde seguir, sin necesidad de re-investigar la arquitectura del punto 2.
