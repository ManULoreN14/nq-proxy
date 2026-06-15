# GUÍA DE VERIFICACIÓN — INDEX v8.0-csv

Esta es la secuencia recomendada para comprobar que todo (backend + frontend)
funciona tras la unificación.

## 0 · Preparación

Verifica que tienes en `C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO\`:

- `actualizar_radar.py` ← unificado, versión `8.0-unificado` (de la sesión anterior)
- `index.html` ← versión `v8.0-csv` (de esta sesión)
- `VERIFY_1_backend.py` ← este script
- `VERIFY_2_dashboard.js` ← este snippet

Y en `DATOS_CSV/`:

- `DIX.csv` (descargado de SqueezeMetrics — el del día más reciente)
- `VIX_History.csv` (CBOE)
- `VVIX_History.csv` (CBOE)
- `skew-history.csv` (CBOE) — opcional, si tienes
- `qqq_quotedata.csv` (Barchart — opciones QQQ del día)
- `COT/*.txt` (CFTC — semanal) — opcional, si tienes

---

## 1 · Ejecutar el backend

```bash
cd C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO
python actualizar_radar.py
```

Deberías ver en el log:

```
NQ RADAR CUANTITATIVO v8.0-unificado - YYYY-MM-DD HH:MM:SS
  CSV local: ACTIVADO (capa autoritativa)
  Carpeta DATOS_CSV: C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO\DATOS_CSV
[1/8] Cargando histórico de datos...
...
[5.6/8] CAPA CSV LOCAL (prevalece sobre APIs)...
   ✅ DIX/GEX local: DIX=XX.X% / GEX=±X.XB$
   ✅ VIX/VVIX/SKEW CBOE: VIX=XX.X / VVIX=XX.X
   ✅ QQQ opciones Barchart: max_pain=XXX, PCR=X.XX
...
[8/8] Exportando JSON...
```

> Si ves un error o aborta por "Mercado cerrado hoy" → es sábado/domingo o festivo.
> Para forzar la ejecución, edita `actualizar_radar.py` y comenta la línea
> `if not mercado_abierto_hoy(): ... sys.exit(0)` SOLO PARA PRUEBAS.

---

## 2 · Verificar el JSON generado

```bash
python VERIFY_1_backend.py
```

Resultado esperado:

```
📂 Leyendo C:\...\datos_radar.json
🕒 Generado: YYYY-MM-DD HH:MM:SS
🔖 Versión:  8.0-unificado

═══ CLAVES NUEVAS V8.0 ═══
═══ CONTENIDO csv_dix_gex ═══
   dix=45.0% · gex_b=7.367B · p_dix=67 · p_gex=93
   histórico: 90 días
═══ CONTENIDO csv_vix_vvix_skew ═══
   vix=18.5 · vvix=86.06 · skew=132.0 · ratio=4.65
   histórico: 90 días
═══ CLAVES LEGACY ═══

═══ RESUMEN ═══
  ✅ clave csv_activo presente
  ✅ clave csv_cot presente
  ✅ ... (todos los demás)

  N/N tests pasados
✅ BACKEND OK
```

Si algún test falla con ❌, mira la línea concreta y ajusta los CSV faltantes.

---

## 3 · Publicar en GitHub

```bash
git add datos_radar.json index.html
git commit -m "v8.0-csv: integración CSV local (DIX/GEX/VIX/VVIX/SKEW)"
git push
```

> Si `actualizar_radar.py` ya hace `git_push()` automáticamente, solo necesitas
> commitear el index.html una vez (no cambiará en cada push).

---

## 4 · Abrir el dashboard en el navegador

Ve a tu URL del dashboard (GitHub Pages o donde lo tengas alojado).
Pulsa "↻ Actualizar" y espera a que cargue.

**Inspección visual rápida:**

### Pane Visión

- 🌑 **Card "DIX · GEX Real — Dark Pools + Gamma de Dealers"** debe aparecer
  entre "GEX Estimado" y "Put/Call Ratio". Debe mostrar:
  - Badge superior derecho con señal (ALCISTA / NEUTRO / BAJISTA)
  - Filas: DIX (con %), GEX (con B$), SPX referencia, textos del backend
  - Footer con fecha del CSV y "✅ Auto · SqueezeMetrics CSV local"
  - Mini-gráfico con dos líneas (verde DIX, ámbar GEX) y leyenda de rangos

- 🌡️ **Card "VIX Term Structure"** debe haber crecido con:
  - VVIX (vol de la vol) — fila nueva
  - Ratio VVIX/VIX — fila nueva
  - CBOE SKEW Index — fila nueva
  - Percentil VIX dice ahora "vs histórico completo CBOE · ~9XXX días"
  - Footer "✅ Auto · CBOE CSV local · YYYY-MM-DD"

### Pane Táctico

- En la card "GEX · DIX · CVD · Breadth — Flujos profundos":
  - Input "GEX exacto (M$)" debe estar **YA RELLENO**
  - Input "DIX %" debe estar **YA RELLENO**
  - Bajo cada uno debe aparecer la interpretación + "✅ Auto · SqueezeMetrics CSV"

### Footer del Dashboard

- Esquina inferior derecha: debe decir `v8.0-csv` (no `v7.0-fase7`)

### Pane Horizontes — Fase 8

- El título "Similitud Fase 8" debe tener DOS chips:
  - `DIX · GEX · VVIX` (azul, como antes)
  - `Motor de similitud histórica` (ámbar, nuevo)
- La descripción debe decir "los valores spot del día … vienen ahora del backend"

---

## 5 · Verificación programática en consola

1. Pulsa **F12** → pestaña **Console**
2. Abre `VERIFY_2_dashboard.js`, copia TODO el contenido
3. Pégalo en la consola y pulsa Enter
4. Lee los `✅ / ❌`

Resultado esperado: todos los tests en ✅.

Si ves ❌ en alguna línea, examina:
- `❌ csv_dix_gex ausente` → falta el CSV en DATOS_CSV/ del backend
- `❌ sdx-dix value vacío` → o falla aplicarDatosRadar, o el JSON no tiene csv_dix_gex
- `❌ Card VIX TS muestra VVIX` → el JSON no tiene csv_vix_vvix_skew

---

## 6 · Test de regresión (opcional — si tienes histórico anterior)

Compara el dashboard nuevo con el anterior. Las cards y datos legacy deben
mostrar EXACTAMENTE los mismos valores (COT, OI por strike, PCR, FRED, etc.).
Lo único que cambia es:

- Aparece la card nueva DIX/GEX
- VIX TS muestra más filas
- DIX/GEX táctico ya viene relleno
- Versión v8.0-csv en el footer

Si algún valor legacy cambia → mira el log del backend, debería tener pistas.

---

## 7 · Operativa diaria desde mañana

```
1. Descarga los CSV del día (DIX, qqq_quotedata, etc.) → DATOS_CSV/
2. python actualizar_radar.py           ← backend hace todo lo demás
3. Recarga el dashboard                  ← visualización lista
```

Si algún día no descargas un CSV, no pasa nada: el dashboard sigue funcionando
con los datos legacy (API CFTC, yfinance, etc.). Las cards CSV mostrarán
"no disponible" pero el resto se mantiene.
