// ╔══════════════════════════════════════════════════════════════════╗
// ║  live-tactico.js — Serverless Function (Vercel Node.js)         ║
// ║  Ruta: nq-proxy/api/live-tactico.js                             ║
// ║                                                                  ║
// ║  Propósito: Fallback intradiario ligero para "Modo Viaje".      ║
// ║  Solo extrae: precio QQQ/NDX, VIX, RSI intradiario.            ║
// ║  NO consulta opciones ni NLP (evita timeout de Vercel).        ║
// ║                                                                  ║
// ║  NOTA: Convertido a Node.js runtime (elimina export config      ║
// ║  edge) para compatibilidad con datos.js / ia.js / manengis.js   ║
// ╚══════════════════════════════════════════════════════════════════╝

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
 * Fix 2.1: pasar símbolo sin pre-codificar (^VIX no %5EVIX) para
 * evitar doble encoding por encodeURIComponent.
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
    precio:    parseFloat((meta.regularMarketPrice || closes.at(-1) || 0).toFixed(2)),
    precioAnt: parseFloat((meta.chartPreviousClose || meta.previousClose || 0).toFixed(2)),
    closes,
    highs:     (quote.high || []).filter(Boolean),
    lows:      (quote.low  || []).filter(Boolean),
  };
}

/** Calcula ROC n días a partir de array de cierres */
function calcROC(closes, n = 5) {
  if (closes.length < n + 1) return null;
  const curr = closes.at(-1);
  const prev = closes.at(-(n + 1));
  return parseFloat(((curr - prev) / prev * 100).toFixed(2));
}

/** Sesgo simplificado basado en RSI + VIX + cambio de precio */
function _sesgoIntradiario({ rsiQQQ, vix, cambioQQQ }) {
  if (!rsiQQQ && !vix) return "sin_datos";
  let puntos = 0;
  if (rsiQQQ !== null) {
    if (rsiQQQ > 70) puntos -= 1;
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

// ── Handler Node.js (compatible con datos.js / ia.js / manengis.js) ─────────

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=30");

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  const t0 = Date.now();

  try {
    // Fix 2.1: ^VIX y ^NDX sin pre-codificar
    const [qqqData, vixData, ndxData, us10Data, dxyData, nqfData] = await Promise.allSettled([
      fetchYahooChart("QQQ",      "5d", "1h"),
      fetchYahooChart("^VIX",     "5d", "1d"),
      fetchYahooChart("^NDX",     "5d", "1d"),
      fetchYahooChart("^TNX",     "5d", "1d"),
      fetchYahooChart("DX-Y.NYB", "5d", "1d"),
      fetchYahooChart("NQ=F",     "5d", "1d"),
    ]);

    let precioQQQ = null, rsiQQQ = null, cambioQQQ = null, rocQQQ = null;
    if (qqqData.status === "fulfilled") {
      const d = qqqData.value;
      precioQQQ = d.precio;
      rsiQQQ    = calcRSI(d.closes);
      rocQQQ    = calcROC(d.closes, 5);
      if (d.precioAnt > 0)
        cambioQQQ = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
    }

    let vix = null, vixCambio = null;
    if (vixData.status === "fulfilled") {
      const d = vixData.value;
      vix = d.precio;
      if (d.precioAnt > 0)
        vixCambio = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
    }

    let precioNDX = null, rsiNDX = null;
    if (ndxData.status === "fulfilled") {
      const d = ndxData.value;
      precioNDX = d.precio;
      rsiNDX    = calcRSI(d.closes);
    }

    // US10Y
    let us10y = null, us10yCambio = null;
    if (us10Data.status === "fulfilled") {
      const d = us10Data.value;
      us10y = d.precio;
      if (d.precioAnt > 0)
        us10yCambio = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
    }

    // DXY
    let dxy = null, dxyCambio = null;
    if (dxyData.status === "fulfilled") {
      const d = dxyData.value;
      dxy = d.precio;
      if (d.precioAnt > 0)
        dxyCambio = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
    }

    // NQ Futuros — intentar NQ=F, si falla usar ^NDX como proxy
    let nqf = null, nqfCambio = null;
    if (nqfData.status === "fulfilled") {
      const d = nqfData.value;
      nqf = d.precio;
      if (d.precioAnt > 0)
        nqfCambio = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
    } else if (ndxData.status === "fulfilled") {
      // Fallback: usar variación del NDX como proxy del futuro NQ
      const d = ndxData.value;
      nqf = d.precio;
      if (d.precioAnt > 0)
        nqfCambio = parseFloat(((d.precio - d.precioAnt) / d.precioAnt * 100).toFixed(2));
    }

    // DXY — fallback: si falla DX-Y.NYB intentar EURUSD inverso
    if (dxy === null) {
      try {
        const eurusdData = await fetchYahooChart("EURUSD=X", "5d", "1d");
        if (eurusdData && eurusdData.precio > 0) {
          // DXY sube cuando EURUSD baja (correlación inversa aproximada)
          dxy = parseFloat((1 / eurusdData.precio * 100).toFixed(2));
          dxyCambio = eurusdData.precioAnt > 0
            ? parseFloat(((eurusdData.precioAnt - eurusdData.precio) / eurusdData.precioAnt * 100).toFixed(2))
            : null;
        }
      } catch(e) { /* sin datos DXY */ }
    }

    res.status(200).json({
      tipo:        "live_intradiario",
      timestamp:   new Date().toISOString(),
      latencia_ms: Date.now() - t0,
      live: {
        precio_qqq: precioQQQ,
        cambio_qqq: cambioQQQ,
        rsi_qqq:    rsiQQQ,
        roc5d:      rocQQQ,
        precio_ndx: precioNDX,
        rsi_ndx:    rsiNDX,
        vix:        vix,
        vix_cambio: vixCambio,
        us10y:      us10y,
        us10y_cambio: us10yCambio,
        dxy:        dxy,
        dxy_cambio: dxyCambio,
        nqf:        nqf,
        nqf_cambio: nqfCambio,
        sesgo_live: _sesgoIntradiario({ rsiQQQ, vix, cambioQQQ }),
      },
      nota: "max_pain / sentiment / cot mantenidos del JSON estático nocturno",
    });

  } catch (err) {
    res.status(500).json({
      tipo:      "live_intradiario",
      error:     err.message,
      timestamp: new Date().toISOString(),
      live:      null,
    });
  }
}
