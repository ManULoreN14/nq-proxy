# SNAPSHOT PARA IA-PROFESOR · 2026-07-06 01:16

> Documento generado automáticamente para pegar en una conversación con una IA y usarla como profesor sobre los datos reales de hoy. No es un volcado de JSON: cada cifra viene con su contexto.

## Resumen del día

- **NDX**: 29329 · **QQQ**: 712.60 · **VIX**: 16.1
- **Régimen macro**: no disponible
- **Score compuesto**: no disponible
- **Exposición recomendada (Kelly ajustado)**: 30%

## Métricas con contexto

- **PCR** = 0.79, percentil 19.3 (bajo) · señal: neutro
- **DIX** = 40.9%, percentil 23.8 (bajo) · señal: distribucion_leve
- **GEX** = 6.86B$ · señal: anclaje
- **VIX Term Structure**: spot=15.8, VX1=17.9 · ¿backwardation? NO (contango)
- **VVIX** = 88.8
- **SKEW** = 150.0
- **COT (leveraged funds)**: neto=-51062, percentil 5.2 (extremadamente bajo) (31.1% largos) · señal: alcista_extremo
- **Índice Sentimiento Contrario** = -0.6 (Neutral) · modo observación, no pesa todavía en el score
- **Flujos ICI (industria completa)**: +65221M en 4 semanas · señal: alcista
- **Amplitud (z-score QQQ vs SMA200)** = 0.45 · señal: normal
- **Detectores de giro**: señal global = neutro

## Señales en conflicto

No se han detectado conflictos evidentes entre las señales principales disponibles hoy.

## Respecto al snapshot anterior

No se encontró un snapshot anterior para comparar — esta sección se completará a partir de la próxima ejecución.

## Glosario

- **PCR**: Put/Call Ratio. Ratio de opciones put vs call negociadas. Alto = mucha cobertura bajista comprada (miedo); bajo = poca cobertura (complacencia). Se usa de forma CONTRARIAN: extremos altos suelen preceder rebotes, extremos bajos suelen preceder caídas.
- **DIX**: Dark Pool Index (SqueezeMetrics). % de volumen que se ejecuta fuera de bolsa (dark pools), donde operan más las instituciones. Alto = acumulación institucional; bajo = distribución.
- **GEX**: Gamma Exposure de los creadores de mercado (dealers). Positivo = los dealers venden en subidas y compran en caídas (amortigua movimientos, mercado 'pegado'). Negativo = compran en subidas y venden en caídas (amplifica movimientos, más volatilidad).
- **VVIX**: Volatilidad del VIX (la 'vol de la vol'). Mide el nerviosismo en el propio mercado de opciones sobre volatilidad. Disparado = pánico; muy bajo = complacencia.
- **VIX Term Structure**: Comparación entre el VIX spot y los futuros de VIX a distintos vencimientos. CONTANGO (futuros > spot) = mercado tranquilo, normal. BACKWARDATION (futuros < spot) = estrés agudo de corto plazo, suele preceder rebotes.
- **COT**: Commitments of Traders (CFTC). Posicionamiento semanal de grandes especuladores (leveraged funds) en futuros. Extremos de posicionamiento se leen de forma CONTRARIAN: muy largos = riesgo de caída (long squeeze); muy cortos = riesgo de subida (short squeeze).
- **SKEW**: Índice SKEW de CBOE. Mide el precio relativo de las opciones muy fuera de dinero (protección ante caídas extremas / cisne negro). Alto = el mercado paga caro por seguros de cola.
- **Sentimiento Contrario**: Oscilador compuesto -100/+100 (DIX+VTS+VVIX/VIX+COT, ponderado por IC medido). Alto = miedo extremo (contrarian alcista); bajo = complacencia extrema (contrarian bajista). Modo observación: no pesa todavía en el score.
- **Flujos ICI**: Entradas/salidas semanales de TODA la industria de fondos+ETF de EE.UU. (Investment Company Institute), no específico de QQQ/Nasdaq. Da contexto de apetito de riesgo agregado del mercado. Sí pesa en el score de flujos.
- **Amplitud de mercado**: Cuántos valores participan de un movimiento del índice, no solo el índice en sí. Precio subiendo con amplitud cayendo (menos valores acompañando) es una divergencia bajista clásica.
- **Kelly / Exposición efectiva**: Porcentaje de capital recomendado según el criterio de Kelly, ajustado por volatilidad. Es el tamaño de posición sugerido, no una orden automática.
- **Régimen macro**: Clasificación del entorno financiero general (expansión / desaceleración / estrés / crisis) a partir de condiciones financieras (NFCI), crédito (HY spread), curva de tipos y liquidez de la Fed.
- **Liquidez neta Fed**: WALCL (balance de la Fed) menos TGA (cuenta del Tesoro) menos RRP (repo inverso). Aproxima cuánta liquidez real hay disponible para los mercados; drenándose = viento en contra estructural.
- **kNN Predictor**: Busca en el histórico los N días más parecidos al día actual (por VIX-TS, VVIX, DIX, GEX, SKEW, RSI, etc.) y resume qué pasó después en esos análogos. Es estadística descriptiva de similitud, no una predicción garantizada.

## Preguntas sugeridas para arrancar el diálogo

- ¿Qué factor domina hoy el score compuesto y por qué?
- ¿Hay alguna señal en conflicto que merezca más atención que las demás?
- Si el Sentimiento Contrario está en zona neutral, ¿qué señales sí aportan información hoy?
- ¿Por qué la exposición recomendada por Kelly es la que es, dado el resto de señales?
