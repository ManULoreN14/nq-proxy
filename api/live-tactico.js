// ╔══════════════════════════════════════════════════════════════════╗
// ║  live-tactico.js — Serverless Function (Vercel)                  ║
// ║  Ruta: nq-proxy/api/live-tactico.js                              ║
// ║                                                                  ║
// ║  Propósito: Fallback intradiario ligero para "Modo Viaje".       ║
// ║  Solo extrae: precio QQQ/NDX, VIX, RSI intradiario.             ║
// ║  NO consulta opciones ni NLP (evita timeout de 5s de Vercel).   ║
// ╚══════════════════════════════════════════════════════════════════╝

export const config = {
  runtime: "edge",           // Edge Runtime = arranque en ~50ms
  maxDuration: 10,           // máx 10 segundos (plan Vercel gratuito = 5s; ajustar)
};

// ── Helpers ─────────────────────────────────────────────────────────────────

/** Calcula RSI de Wilder a partir de un array de cierres */
function calcRSI(closes, period = 14) {
  if (closes.length < period * 2) return null;
  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) avgGain += d; else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
  }
  if (avgLoss === 0) return 100;
  return parseFloat((100 - 100 / (1 + avgGain / avgLoss)).toFixed(2));
}

/**
 * Llama a Yahoo Finance chart API v8 (sin API key, endpoint público).
 * Retorna { precio, closes[], highs[], lows[], timestamps[] }
 */
async function fetchYahooChart(symbol, range = "5d", interval = "1h") {
  const url =
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}` +
    `?range=${range}&interval=${interval}&includePrePost=true`;

  const res = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      "Accept": "application/json",
    },
  });

  if (!res.ok) throw new Error(`Yahoo ${symbol} HTTP ${res.status}`);

  const json = await res.json();
  const result = json?.chart?.result?.[0];
  if (!result) throw new Error(`Sin datos para ${symbol}`);

  const meta   = result.meta;
  const quote  = result.indicators?.quote?.[0] || {};
  const closes = (quote.close || []).filter(Boolean);

  return {
    symbol,
    precio:      parseFloat((meta.regularMarketPrice || closes.at(-1) || 0).toFixed(2)),
    precioAnt:   parseFloat((meta.chartPreviousClose || meta.previousClose || 0).toFixed(2)),
    closes,
    highs:       (quote.high || []).filter(Boolean),
    lows:        (quote.low  || []).filter(Boolean),
    timestamps:  result.timestamp || [],
  };
}

/** Calcula ROC n días a partir de array de cierres diarios */
function calcROC(closes, n = 5) {
  if (closes.length < n + 1) return null;
  const curr = closes.at(-1);
  const prev = closes.at(-(n + 1));
  return parseFloat(((curr - prev) / prev * 100).toFixed(2));
}

// ── Handler principal ────────────────────────────────────────────────────────

export default async function handler(req) {
  // CORS — permitir llamadas desde el frontend nqrisk
  const headers = {
    "Content-Type":                "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Cache-Control":               "s-maxage=60, stale-while-revalidate=30",
  };

  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers });
  }

  const t0 = Date.now();

  try {
    // ── Fetch paralelo de QQQ, VIX (^VIX), NDX (^NDX) ───────────────────────
    const [qqqData, vixData, ndxData] = await Promise.allSettled([
      fetchYahooChart("QQQ",  "5d", "1h"),
      fetchYahooChart("%5EVIX", "5d", "1d"),
      fetchYahooChart("%5ENDX", "5d", "1d"),
    ]);

    // ── QQQ ──────────────────────────────────────────────────────────────────
    let precioQQQ = null, rsiQQQ = null, cambioQQQ = null, rocQQQ = null;

    if (qqqData.status === "fulfilled") {
      const d = qqqData.value;
      precioQQQ  = d.precio;
      rsiQQQ     = calcRSI(d.closes);
      rocQQQ     = calcROC(d.closes, 5);
      if (d.precioAnt > 0) {
        cambioQQQ = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
      }
    }

    // ── VIX ──────────────────────────────────────────────────────────────────
    let vix = null, vixCambio = null;

    if (vixData.status === "fulfilled") {
      const d = vixData.value;
      vix = d.precio;
      if (d.precioAnt > 0) {
        vixCambio = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
      }
    }

    // ── NDX ──────────────────────────────────────────────────────────────────
    let precioNDX = null, rsiNDX = null;

    if (ndxData.status === "fulfilled") {
      const d = ndxData.value;
      precioNDX = d.precio;
      rsiNDX    = calcRSI(d.closes);
    }

    // ── Sesgo intradiario simplificado ────────────────────────────────────────
    const sesgo = _sesgoIntradiario({ rsiQQQ, vix, cambioQQQ });

    // ── Respuesta ─────────────────────────────────────────────────────────────
    const payload = {
      tipo:         "live_intradiario",
      timestamp:    new Date().toISOString(),
      latencia_ms:  Date.now() - t0,

      // ── Variables que el frontend sobreescribirá en pantalla ─────────────
      live: {
        precio_qqq:   precioQQQ,
        cambio_qqq:   cambioQQQ,      // % vs. cierre anterior
        rsi_qqq:      rsiQQQ,
        roc5d:        rocQQQ,
        precio_ndx:   precioNDX,
        rsi_ndx:      rsiNDX,
        vix:          vix,
        vix_cambio:   vixCambio,
        sesgo_live:   sesgo,
      },

      // ── Nota: estos campos NO se actualizan (se mantienen del JSON nocturno)
      nota: "max_pain / sentiment / cot mantenidos del JSON estático nocturno",
    };

    return new Response(JSON.stringify(payload, null, 2), {
      status: 200,
      headers,
    });

  } catch (err) {
    return new Response(
      JSON.stringify({
        tipo:      "live_intradiario",
        error:     err.message,
        timestamp: new Date().toISOString(),
        live:      null,
      }),
      { status: 500, headers }
    );
  }
}

/** Sesgo simplificado basado en RSI + VIX + cambio de precio */
function _sesgoIntradiario({ rsiQQQ, vix, cambioQQQ }) {
  if (!rsiQQQ && !vix) return "sin_datos";

  let puntos = 0;

  if (rsiQQQ !== null) {
    if (rsiQQQ > 70) puntos -= 1;
    else if (rsiQQQ > 60) puntos += 0;
    else if (rsiQQQ < 40) puntos += 1;
    else if (rsiQQQ < 30) puntos += 2;
  }

  if (vix !== null) {
    if (vix > 25) puntos += 1;
    if (vix > 35) puntos += 1;
    if (vix < 15) puntos -= 1;
  }

  if (cambioQQQ !== null) {
    if (cambioQQQ > 1.5) puntos -= 1;
    if (cambioQQQ < -1.5) puntos += 1;
  }

  if (puntos >= 2)  return "cauto";
  if (puntos <= -2) return "euforia";
  if (puntos === 1) return "neutral_cauto";
  return "neutral";
}
