# GUÍA PARA ARREGLAR EL PUSH — PASO A PASO

## ❌ Lo que pasó

Mirando los logs de tus comandos, subiste a `nq-proxy` versiones **viejas e incorrectas** de los dos `.py`:

| Commit | Líneas modificadas | Era el de... | Lo correcto sería... |
|---|---|---|---|
| `88863a9` motor_manengis.py | +104 / -26 | Entrega 3 antigua (auditoría inicial) | Sprints 1, 3, 4, 5 con +250 líneas aprox |
| `d9f15a4` actualizar_radar.py | +125 / -36 | Entrega 2 antigua (5 bugs) | Sprints 1, 2, 5 con +400 líneas aprox |

**El `index.html` (dashboard) SÍ subió bien** (commit `ed26bd0`, 116+48 = 164 líneas modificadas) — eso es correcto.

## ✅ Cómo arreglarlo

### Paso 1 — Copiar los archivos correctos a la carpeta

Coge los dos archivos que acabo de darte ahora mismo en este chat:
- `actualizar_radar.py` (ahora con **8085 líneas**, incluye Sprint 1-5 completos + D.3 aviso CSV Barchart obsoleto)
- `motor_manengis.py` (1377 líneas, con Sprints 1, 3, 4, 5 completos)

Y **sobrescribe** los archivos de `C:\Users\m21lo\nq-proxy\` (los que están allí ahora son viejos).

### Paso 2 — Verificar antes de commitear

```cmd
cd C:\Users\m21lo\nq-proxy

git status
```

Deberías ver:
```
modified:   actualizar_radar.py
modified:   motor_manengis.py
```

Si los ves modificados, sigue. Si no aparecen modificados, es que los archivos en disco ya son los correctos (no copiaste encima) o git no detectó cambios.

### Paso 3 — Hacer el commit y push

```cmd
git add actualizar_radar.py motor_manengis.py

git commit -m "Sprints 1-5 COMPLETOS: boost x1.4 eliminado, NDX100 bulk, risk_score factores reductores, kNN unificado, RSI Wilder, regimen renombrado, COT canonico, CSV Barchart aviso obsoleto"

git stash
git pull
git stash pop
git push origin main
```

### Paso 4 — Verificación en GitHub

Después del push, ve al navegador y abre estos dos enlaces:

**1. `actualizar_radar.py`:**
https://github.com/ManULoreN14/nq-proxy/blob/main/actualizar_radar.py

Usa Ctrl+F para buscar estos textos. **TODOS deben aparecer:**
1. `Sprint 1 A.1: ANTES había un boost artificial`
2. `Sprint 1 D.1: ANTES descargaba los 100 tickers UNO POR UNO`
3. `Sprint 2 A.2: clarificar qué métricas están INVERTIDAS`
4. `momentum_vix_corto_señal`
5. `señal_percentil`
6. `Sprint 5: CNY=X cotiza USD/CNY`
7. `Sprint 5 D.3: avisa si el CSV tiene más de 7 días`
8. `csv_dias_antiguedad`
9. En la lista NDX100: `APP`, `PLTR`, `AXON`, `ARGX` (los nuevos)
10. NO debe aparecer en la lista: `LCID`, `JD`, `BMRN` (los viejos)

**2. `motor_manengis.py`:**
https://github.com/ManULoreN14/nq-proxy/blob/main/motor_manengis.py

Busca:
1. `Sprint 1 B.1: FACTORES REDUCTORES`
2. `risk -= 0.5`
3. `Sprint 3 C.1: PRIORIZAR el kNN del radar`
4. `radar.knn_predictor`
5. `Sprint 3 C.2: "breadth" eliminada del conjunto`
6. `Sprint 4 E.1: ANTES motor usaba rolling().mean()`
7. `ewm(com=n-1, adjust=False).mean()`
8. `Sprint 5 E.2: sentimiento es un placeholder PERMANENTE`

**Si encuentras los 10+8 textos → todo correcto, el cron de hoy a las 22:30 Madrid usará las versiones finales.**

**Si NO encuentras alguno → no se subió bien y hay que repetir.**

---

## Sobre los dos puntos que NO toqué — decisión final

### E.3 — Color matriz `medio-alcista` (ámbar vs verde)

**Decisión: lo dejo ámbar como está.**

Mi razonamiento:
- Tu matriz tiene una lectura visual por filas coherente:
  - Fila `bajo-*`: verde y ámbar (riesgo bajo, todo va bien)
  - Fila `medio-*`: ámbar (zona estándar, precaución estructural)
  - Fila `alto-*`: roja (riesgo alto, reducir)
- El **risk bucket** (filas) define el tono predominante, no el radar (columnas)
- Si pongo `medio-alcista` en verde, **rompo la lectura por filas** — la fila medio dejaría de ser homogénea y el ojo perdería la referencia
- "Riesgo medio" significa precaución por definición — el ámbar refleja esa precaución incluso cuando el radar dice "alcista"

**Tu decisión, no la mía. Pero mi recomendación profesional es: déjala ámbar.**

### D.3 — Automatizar descarga Barchart CSV

**Decisión: NO automatizar la descarga, pero AÑADIR aviso si el CSV está obsoleto.**

Razón:
- Automatizar requiere login a Barchart (no exponen CSV gratis)
- Eso significa guardar credenciales como GitHub Secret → superficie de ataque
- Para un dato que solo se refresca 1-2 veces por semana → riesgo > beneficio

**Lo que SÍ he hecho ahora (incluido en el `actualizar_radar.py` actualizado):**
- Nueva línea en `leer_qqq_opciones_csv` que mira la fecha del archivo en disco
- Si tiene más de 7 días → log con aviso `⚠ AVISO: qqq_quotedata.csv tiene X.X días`
- En el JSON añade campos `csv_dias_antiguedad` y `csv_obsoleto: true/false`
- Tú puedes usar esos campos en el dashboard si quieres mostrar un aviso visual (no lo he tocado en `index.html` para no inflar el cambio — si lo quieres después te lo añado)

Así sabes cuándo toca actualizar el CSV manualmente sin que te pase desapercibido.

---

## Limpieza opcional pero recomendada

En el `git status` veo que tienes muchos archivos basura sin trackear en `C:\Users\m21lo\nq-proxy\`:

```
actualizar_radar CONSERVAR.py
actualizar_radarANTES DE HMM.py
actualizar_radarBORRAR.py
actualizar_radarCONSERVAR.py
actualizar_radarPENULTIMO.py
actualizar_radarPORSIACA.py
motor_manengisCONSERVAR.py
indexANTES CAMBIO PESTAÑAS.html  (en dashboard)
indexANTESDE HMM.html
indexBORRAR.html
```

Esto es un **enorme riesgo de confusión** — la próxima vez que hagas un cambio puedes copiar el archivo equivocado y mezclar versiones. Te recomiendo:

1. Crear UNA carpeta `_backups/` fuera del repo (por ejemplo `C:\Users\m21lo\BACKUPS_NQ\`)
2. Mover allí TODOS esos archivos `*BORRAR*`, `*CONSERVAR*`, `*ANTES*`
3. La carpeta `nq-proxy` debe tener únicamente: `actualizar_radar.py`, `motor_manengis.py`, `actualizar_datos.yml`, los CSV y los JSON, y poco más

Así git nunca se confunde y tú tampoco.

Si quieres mantenerlos como histórico, hazlo **fuera del repo**, no dentro.
