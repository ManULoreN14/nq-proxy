// api/datos.js — Proxy datos mercado + indicadores técnicos automáticos
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET');
  res.setHeader('Cache-Control', 's-maxage=300');

  // ── Helpers de cálculo técnico ──────────────────────────────
  function calcRSI(closes, period = 14) {
    if (closes.length < period + 1) return null;
    let gains = 0, losses = 0;
    for (let i = closes.length - period; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff >= 0) gains += diff; else losses -= diff;
    }
    const avgGain = gains / period;
    const avgLoss = losses / period;
    if (avgLoss === 0) return 100;
    const rs = avgGain / avgLoss;
    return parseFloat((100 - 100 / (1 + rs)).toFixed(2));
  }

  function calcEMA(closes, period) {
    if (closes.length < period) return null;
    const k = 2 / (period + 1);
    let ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < closes.length; i++) {
      ema = closes[i] * k + ema * (1 - k);
    }
    return parseFloat(ema.toFixed(2));
  }

  function calcSMA(closes, period) {
    if (closes.length < period) return null;
    const slice = closes.slice(-period);
    return parseFloat((slice.reduce((a, b) => a + b, 0) / period).toFixed(2));
  }

  function calcMACD(closes) {
    if (closes.length < 26) return null;
    const ema12 = calcEMA(closes, 12);
    const ema26 = calcEMA(closes, 26);
    if (!ema12 || !ema26) return null;
    const macdLine = parseFloat((ema12 - ema26).toFixed(2));
    // Signal line: EMA9 del MACD (aproximación)
    const macdValues = [];
    for (let i = 26; i <= closes.length; i++) {
      const e12 = calcEMA(closes.slice(0, i), 12);
      const e26 = calcEMA(closes.slice(0, i), 26);
      if (e12 && e26) macdValues.push(e12 - e26);
    }
    const signal = macdValues.length >= 9 ? calcEMA(macdValues, 9) : null;
    const histogram = signal !== null ? parseFloat((macdLine - signal).toFixed(2)) : null;
    return { macd: macdLine, signal: signal ? parseFloat(signal.toFixed(2)) : null, histogram };
  }

  function calcATR(highs, lows, closes, period = 14) {
    if (!highs || !lows || closes.length < period + 1) return null;
    const trs = [];
    for (let i = 1; i < closes.length; i++) {
      const tr = Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      );
      trs.push(tr);
    }
    const atr = trs.slice(-period).reduce((a, b) => a + b, 0) / period;
    return parseFloat(atr.toFixed(2));
  }

  function calcAccDis(highs, lows, closes, volumes) {
    if (!highs || !lows || !volumes || closes.length < 2) return null;
    let accDis = 0;
    for (let i = 0; i < closes.length; i++) {
      const range = highs[i] - lows[i];
      if (range === 0) continue;
      const mfm = ((closes[i] - lows[i]) - (highs[i] - closes[i])) / range;
      accDis += mfm * (volumes[i] || 0);
    }
    // Devolver tendencia: positivo = acumulación, negativo = distribución
    const recent = accDis;
    return { value: parseFloat(accDis.toFixed(0)), trend: recent >= 0 ? 'acumulacion' : 'distribucion' };
  }

  // ── Fetch Yahoo Finance ──────────────────────────────────────
  async function fetchYahoo(symbol, range = '1y') {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=${range}`;
    const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    const data = await r.json();
    const result = data?.chart?.result?.[0];
    if (!result) return null;
    const quote = result.indicators?.quote?.[0];
    return {
      closes: (quote?.close ?? []).filter(v => v !== null),
      highs:  (quote?.high  ?? []).filter(v => v !== null),
      lows:   (quote?.low   ?? []).filter(v => v !== null),
      volumes:(quote?.volume ?? []).filter(v => v !== null),
    };
  }

  const resultado = {};

  // ── Datos básicos (VIX, VXN, NQ, US10Y, DXY) ────────────────
  const basicSymbols = { vix: '^VIX', vxn: '^VXN', nq: 'NQ=F', us10: '^TNX', dxy: 'DX-Y.NYB' };
  await Promise.all(Object.entries(basicSymbols).map(async ([key, sym]) => {
    try {
      const d = await fetchYahoo(sym, '5d');
      if (!d || d.closes.length < 2) return;
      const last = d.closes[d.closes.length - 1];
      const prev = d.closes[d.closes.length - 2];
      const chg = ((last - prev) / prev * 100);
      resultado[key] = { v: parseFloat(last.toFixed(2)), chg: parseFloat(chg.toFixed(2)) };
    } catch { resultado[key] = null; }
  }));

  // ── Indicadores técnicos del NDX ────────────────────────────
  try {
    const ndx = await fetchYahoo('^NDX', '1y');
    if (ndx && ndx.closes.length >= 50) {
      const closes = ndx.closes;
      const precio = closes[closes.length - 1];

      const rsi14   = calcRSI(closes, 14);
      const ema20   = calcEMA(closes, 20);
      const ema50   = calcEMA(closes, 50);
      const sma20   = calcSMA(closes, 20);
      const sma50   = calcSMA(closes, 50);
      const sma200  = calcSMA(closes, 200);
      const macdObj = calcMACD(closes);
      const atr14   = calcATR(ndx.highs, ndx.lows, closes, 14);
      const accDis  = calcAccDis(ndx.highs, ndx.lows, closes, ndx.volumes);

      // RSI de los últimos 5 días para detectar divergencias y momentum
      const rsiHistorial = [];
      for (let i = Math.max(closes.length - 5, 15); i <= closes.length; i++) {
        const r = calcRSI(closes.slice(0, i), 14);
        if (r !== null) rsiHistorial.push(r);
      }

      // Detectar divergencia bajista: precio hace máximos pero RSI no
      let divergenciaBajista = false;
      if (rsiHistorial.length >= 3) {
        const precioSubiendo = closes[closes.length-1] > closes[closes.length-3];
        const rsiSubiendo = rsiHistorial[rsiHistorial.length-1] > rsiHistorial[rsiHistorial.length-3];
        divergenciaBajista = precioSubiendo && !rsiSubiendo && rsi14 > 65;
      }

      // Días consecutivos con RSI > 80
      let diasRsiAlto = 0;
      for (let i = rsiHistorial.length - 1; i >= 0; i--) {
        if (rsiHistorial[i] > 80) diasRsiAlto++;
        else break;
      }

      // Tendencia RSI (subiendo o bajando)
      const tendenciaRsi = rsiHistorial.length >= 3
        ? (rsiHistorial[rsiHistorial.length-1] > rsiHistorial[rsiHistorial.length-3] ? 'subiendo' : 'bajando')
        : 'neutro';

      // Alerta RSI final
      let alertaRsi = 'ninguna';
      if (rsi14 > 85) alertaRsi = 'extrema';
      else if (rsi14 > 80 && diasRsiAlto >= 3) alertaRsi = 'alta';
      else if (divergenciaBajista) alertaRsi = 'divergencia';
      else if (rsi14 > 70 && tendenciaRsi === 'bajando') alertaRsi = 'moderada';

      // Señales interpretadas
      const señales = {
        rsi: rsi14 !== null ? {
          valor: rsi14,
          estado: rsi14 > 70 ? 'sobrecompra' : rsi14 < 30 ? 'sobreventa' : 'neutro',
          tendencia: tendenciaRsi,
          divergenciaBajista,
          diasRsiAlto,
          alertaRsi
        } : null,
        ema20: ema20 !== null ? {
          valor: ema20,
          precioVsEma: precio > ema20 ? 'por_encima' : 'por_debajo'
        } : null,
        ema50: ema50 !== null ? {
          valor: ema50,
          precioVsEma: precio > ema50 ? 'por_encima' : 'por_debajo',
          cruceEmas: ema20 !== null ? (ema20 > ema50 ? 'alcista' : 'bajista') : null
        } : null,
        sma20: sma20 !== null ? {
          valor: sma20,
          precioVsSma: precio > sma20 ? 'por_encima' : 'por_debajo',
          distanciaPct: parseFloat(((precio - sma20) / sma20 * 100).toFixed(2))
        } : null,
        sma50: sma50 !== null ? {
          valor: sma50,
          precioVsSma: precio > sma50 ? 'por_encima' : 'por_debajo',
          distanciaPct: parseFloat(((precio - sma50) / sma50 * 100).toFixed(2))
        } : null,
        sma200: sma200 !== null ? {
          valor: sma200,
          precioVsSma: precio > sma200 ? 'por_encima' : 'por_debajo',
          distanciaPct: parseFloat(((precio - sma200) / sma200 * 100).toFixed(2))
        } : null,
        macd: macdObj,
        atr: atr14 !== null ? { valor: atr14 } : null,
        accdis: accDis,
        precio: parseFloat(precio.toFixed(2))
      };

      resultado.tecnicos = señales;
    }
  } catch (e) {
    resultado.tecnicos = null;
  }

  if (resultado.nq) resultado.nq.isChg = true;

  // Put/Call Ratios del CBOE — via CSV estático (más fiable que scraping HTML)
  try {
    // Intentar primero con el CSV de la CDN del CBOE
    const csvUrls = [
      'https://cdn.cboe.com/api/global/us_indices/daily_prices/PC_STATS.csv',
      'https://www.cboe.com/data/pc_stats.csv'
    ];
    let pcrData = null;
    for (const url of csvUrls) {
      try {
        const r = await fetch(url, {
          headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'text/csv,text/plain' }
        });
        if (!r.ok) continue;
        const csv = await r.text();
        const lines = csv.trim().split('\n').filter(l => l.trim());
        if (lines.length < 2) continue;
        // Cabecera
        const headers = lines[0].split(',').map(h => h.trim().toLowerCase().replace(/['"]/g,''));
        // Última línea con datos
        const lastLine = lines[lines.length - 1];
        const vals = lastLine.split(',').map(v => v.trim().replace(/['"]/g,''));
        const row = {};
        headers.forEach((h, i) => row[h] = vals[i]);
        // Mapear columnas — el CSV del CBOE tiene distintos nombres posibles
        const getVal = (...keys) => {
          for (const k of keys) {
            const found = Object.keys(row).find(h => h.includes(k));
            if (found && row[found] && !isNaN(row[found])) return parseFloat(parseFloat(row[found]).toFixed(2));
          }
          return null;
        };
        pcrData = {
          equity: getVal('equity', 'eq_pc', 'equity_pc'),
          total:  getVal('total', 'tot_pc', 'total_pc', 'pc_ratio'),
          index:  getVal('index', 'idx_pc', 'index_pc'),
          spx:    getVal('spx', 'spxw', 'spx_pc'),
          fecha:  row['date'] || row['as_of'] || 'hoy',
          fuente: 'csv'
        };
        if (pcrData.total || pcrData.equity) break;
      } catch {}
    }
    resultado.pcr = pcrData;
  } catch(e) {
    resultado.pcr = null;
  }

  // Máximo y mínimo 90 días del NDX para Fibonacci + Zonas de liquidez
  try {
    const ndxFib = await fetchYahoo('^NDX', '1y');
    if (ndxFib && ndxFib.closes.length > 0) {
      const highs = ndxFib.highs.filter(v=>v);
      const lows  = ndxFib.lows.filter(v=>v);
      const closes = ndxFib.closes.filter(v=>v);
      const n = closes.length;

      resultado.max90 = parseFloat(Math.max(...highs.slice(-90)).toFixed(2));
      resultado.min90 = parseFloat(Math.min(...lows.slice(-90)).toFixed(2));

      // Zonas de liquidez — máximos y mínimos de distintos períodos
      const precio = closes[n-1];

      // Máximos recientes (liquidez arriba)
      const max20  = parseFloat(Math.max(...highs.slice(-20)).toFixed(2));
      const max50  = parseFloat(Math.max(...highs.slice(-50)).toFixed(2));
      const max90v = parseFloat(Math.max(...highs.slice(-90)).toFixed(2));

      // Mínimos recientes (liquidez abajo)
      const min20  = parseFloat(Math.min(...lows.slice(-20)).toFixed(2));
      const min50  = parseFloat(Math.min(...lows.slice(-50)).toFixed(2));
      const min90v = parseFloat(Math.min(...lows.slice(-90)).toFixed(2));

      // Detectar igualdades (máximos/mínimos muy cercanos = alta liquidez)
      // Buscar máximos locales en ventana de 5 días
      const maxLocales = [];
      const minLocales = [];
      for (let i = 5; i < n-5; i++) {
        const h = highs[i];
        const l = lows[i];
        const esMaxLocal = highs.slice(i-5,i).every(v=>v<=h) && highs.slice(i+1,i+6).every(v=>v<=h);
        const esMinLocal = lows.slice(i-5,i).every(v=>v>=l) && lows.slice(i+1,i+6).every(v=>v>=l);
        if (esMaxLocal) maxLocales.push(h);
        if (esMinLocal) minLocales.push(l);
      }

      // ── PUNTO 3: Swings recientes (últimos 20 días pesan más) ──
      // Detectar swing highs/lows en ventana corta (5d) y larga (10d)
      const swingHighs = [];
      const swingLows  = [];
      for (let i = 3; i < n-3; i++) {
        const h = highs[i];
        const l = lows[i];
        // Swing high: máximo local en ventana ±3
        if (highs.slice(i-3,i).every(v=>v<h) && highs.slice(i+1,i+4).every(v=>v<h)) {
          swingHighs.push({ val: h, idx: i, reciente: i >= n-20 });
        }
        // Swing low: mínimo local en ventana ±3
        if (lows.slice(i-3,i).every(v=>v>l) && lows.slice(i+1,i+4).every(v=>v>l)) {
          swingLows.push({ val: l, idx: i, reciente: i >= n-20 });
        }
      }

      // ── PUNTO 1: Igualdades (equal highs/lows) con umbral ±0.2% ──
      const detectarIgualdades = (arr, esHigh) => {
        const grupos = [];
        for (const s of arr) {
          const g = grupos.find(g => Math.abs(g.val - s.val)/g.val < 0.002); // ±0.2%
          if (g) {
            g.count++;
            g.val = (g.val * (g.count-1) + s.val) / g.count;
            g.tieneReciente = g.tieneReciente || s.reciente;
            g.indices.push(s.idx);
          } else {
            grupos.push({ val: parseFloat(s.val.toFixed(2)), count: 1, tieneReciente: s.reciente, indices: [s.idx] });
          }
        }
        // Ordenar: primero igualdades reales (count>=2), luego por reciente
        return grupos
          .sort((a,b) => {
            if (b.count !== a.count) return b.count - a.count;
            return b.tieneReciente - a.tieneReciente;
          })
          .slice(0, 6)
          .map(g => ({
            nivel: parseFloat(g.val.toFixed(2)),
            igualdad: g.count >= 2,  // true = equal high/low real
            count: g.count,
            reciente: g.tieneReciente,
            fuerza: g.count >= 3 ? 'alta' : g.count === 2 ? 'media' : g.tieneReciente ? 'media' : 'baja',
            distPct: parseFloat(((g.val - precio)/precio*100).toFixed(2))
          }));
      };

      const zonasArriba = detectarIgualdades(swingHighs.filter(s => s.val > precio), true);
      const zonasAbajo  = detectarIgualdades(swingLows.filter(s => s.val < precio), false);

      resultado.liquidez = {
        precio,
        arriba: {
          max20, max50, max90: max90v,
          swingsRecientes: swingHighs.filter(s => s.val > precio && s.reciente).slice(-3).map(s => s.val),
          zonas: zonasArriba
        },
        abajo: {
          min20, min50, min90: min90v,
          swingsRecientes: swingLows.filter(s => s.val < precio && s.reciente).slice(-3).map(s => s.val),
          zonas: zonasAbajo
        }
      };
    }
  } catch(e) { console.error('Liquidez error:', e); }

  // Cierres históricos del NDX para backtesting automático
  // Si se pasa ?fechas=2026-05-04,2026-05-03 devuelve los cierres de esos días
  const fechasParam = req.query?.fechas;
  if (fechasParam) {
    const fechas = fechasParam.split(',').filter(f => f.match(/^\d{4}-\d{2}-\d{2}$/));
    if (fechas.length > 0) {
      try {
        const ndxHist = await fetchYahoo('^NDX', '3mo');
        if (ndxHist && ndxHist.closes.length > 0) {
          const ndxRaw = await fetch(
            `https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX?interval=1d&range=3mo`,
            { headers: { 'User-Agent': 'Mozilla/5.0' } }
          );
          const ndxData = await ndxRaw.json();
          const timestamps = ndxData?.chart?.result?.[0]?.timestamp ?? [];
          const closes = ndxData?.chart?.result?.[0]?.indicators?.quote?.[0]?.close ?? [];
          
          const cierresPorFecha = {};
          timestamps.forEach((ts, i) => {
            const fecha = new Date(ts * 1000).toISOString().slice(0, 10);
            if (closes[i] !== null) cierresPorFecha[fecha] = parseFloat(closes[i].toFixed(2));
          });

          resultado.cierresHistoricos = {};
          fechas.forEach(f => {
            resultado.cierresHistoricos[f] = cierresPorFecha[f] || null;
          });
        }
      } catch (e) {
        resultado.cierresHistoricos = null;
      }
    }
  }

  res.status(200).json(resultado);
}
