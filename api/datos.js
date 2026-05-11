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

  // MAX PAIN — calculado desde cadena de opciones del QQQ (Yahoo Finance)
  try {
    // QQQ es el ETF del Nasdaq 100 — sus opciones determinan el Max Pain del índice
    const expUrl = 'https://query1.finance.yahoo.com/v7/finance/options/QQQ';
    const expResp = await fetch(expUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    const expData = await expResp.json();
    const expirations = expData?.optionChain?.result?.[0]?.expirationDates || [];

    if (expirations.length > 0) {
      // Usar la expiración más próxima (weekly)
      const nextExp = expirations[0];
      const optUrl = `https://query1.finance.yahoo.com/v7/finance/options/QQQ?date=${nextExp}`;
      const optResp = await fetch(optUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
      const optData = await optResp.json();
      const chain = optData?.optionChain?.result?.[0];

      if (chain) {
        const calls = chain.options?.[0]?.calls || [];
        const puts  = chain.options?.[0]?.puts  || [];
        const precio = chain.quote?.regularMarketPrice;

        // Calcular Max Pain matemáticamente
        // Para cada strike, calcular el dolor total (suma de valor intrínseco de todas las opciones)
        const strikes = [...new Set([
          ...calls.map(c => c.strike),
          ...puts.map(p => p.strike)
        ])].sort((a,b) => a-b);

        let minDolor = Infinity;
        let maxPain = precio;

        for (const strike of strikes) {
          let dolor = 0;
          // Dolor de calls: suma de (strike_call - strike_test) * OI para calls ITM
          for (const call of calls) {
            if (call.strike < strike) {
              dolor += (strike - call.strike) * (call.openInterest || 0);
            }
          }
          // Dolor de puts: suma de (strike_test - strike_put) * OI para puts ITM
          for (const put of puts) {
            if (put.strike > strike) {
              dolor += (put.strike - strike) * (put.openInterest || 0);
            }
          }
          if (dolor < minDolor) {
            minDolor = dolor;
            maxPain = strike;
          }
        }

        const distPct = parseFloat(((maxPain - precio) / precio * 100).toFixed(2));
        const expDate = new Date(nextExp * 1000).toISOString().slice(0,10);

        resultado.maxpain = {
          valor: maxPain,
          precio: parseFloat(precio.toFixed(2)),
          distPct,
          expiracion: expDate,
          señal: distPct > 3 ? 'acumulacion' : distPct < -3 ? 'distribucion' : 'neutro',
          descripcion: distPct > 3
            ? 'Precio bajo Max Pain — dealers incentivados a subir (acumulación)'
            : distPct < -3
            ? 'Precio sobre Max Pain — dealers incentivados a bajar (distribución)'
            : 'Precio cerca del Max Pain — dealers neutrales'
        };
      }
    }
  } catch(e) { resultado.maxpain = null; }

  // DATOS MACRO FRED — Federal Reserve Economic Data
  try {
    const FRED_KEY = 'f15ed9ee86d337183138a81bfd4952cb';
    const fredFetch = async (series) => {
      const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${series}&api_key=${FRED_KEY}&file_type=json&limit=2&sort_order=desc`;
      const r = await fetch(url);
      const d = await r.json();
      const obs = d?.observations?.filter(o => o.value !== '.');
      if (!obs || obs.length === 0) return null;
      return {
        actual: parseFloat(parseFloat(obs[0].value).toFixed(4)),
        anterior: obs[1] ? parseFloat(parseFloat(obs[1].value).toFixed(4)) : null,
        fecha: obs[0].date,
        tendencia: obs[1] ? (parseFloat(obs[0].value) > parseFloat(obs[1].value) ? 'subiendo' : 'bajando') : null
      };
    };

    const [walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y] = await Promise.all([
      fredFetch('WALCL'),         // Balance Fed
      fredFetch('FEDFUNDS'),      // Fed Funds Rate
      fredFetch('BAMLH0A0HYM2'), // HY Credit Spread
      fredFetch('NFCI'),          // Condiciones financieras
      fredFetch('T10Y2Y'),        // Curva 10Y-2Y
      fredFetch('T10Y3M'),        // Curva 10Y-3M (más fiable para recesión)
      fredFetch('SOFR'),          // Tipo repo SOFR
      fredFetch('T5Y5Y')          // Expectativas largo plazo
    ]);

    // Estrés interbancario: SOFR vs Fed Funds
    let sofrSpread = null;
    if (sofr && fedfunds) {
      sofrSpread = parseFloat((sofr.actual - fedfunds.actual).toFixed(3));
    }

    // Estado curva de tipos
    const estadoCurva = (t10y3m && t10y2y) ? {
      t10y2y: t10y2y.actual,
      t10y3m: t10y3m.actual,
      invertida_2y: t10y2y.actual < 0,
      invertida_3m: t10y3m.actual < 0,
      // La 10Y-3M invertida es la más fiable históricamente (Fed Cleveland)
      señalRecesion: t10y3m.actual < -0.5 ? 'alta' : t10y3m.actual < 0 ? 'moderada' : 'baja',
      descripcion: t10y3m.actual < -0.5 ? '⚠️ Curva 10Y-3M muy invertida — señal recesión alta fiabilidad' :
                   t10y3m.actual < 0 ? 'Curva 10Y-3M invertida — vigilar' :
                   t10y2y.actual < 0 ? 'Curva 10Y-2Y invertida, 10Y-3M normal — señal mixta' :
                   'Curva normal — sin señal de recesión'
    } : null;

    const interpretarFred = (walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y, sofrSpread) => {
      let señales = [];
      let score = 0;

      if (walcl) {
        const alcista = walcl.tendencia === 'subiendo';
        score += alcista ? 1 : -1;
        señales.push({ ind: 'Balance Fed', val: (walcl.actual/1000000).toFixed(2) + 'T', tend: walcl.tendencia, señal: alcista ? 'alcista' : 'bajista', desc: alcista ? 'Fed expandiendo balance — liquidez positiva para activos de riesgo' : 'Fed contrayendo balance (QT) — reducción de liquidez' });
      }
      if (fedfunds) {
        const alcista = fedfunds.actual < 4;
        const bajista = fedfunds.actual > 5;
        score += alcista ? 1 : bajista ? -1 : 0;
        señales.push({ ind: 'Fed Funds Rate', val: fedfunds.actual + '%', tend: fedfunds.tendencia, señal: alcista ? 'alcista' : bajista ? 'bajista' : 'neutro', desc: bajista ? 'Tipos restrictivos — presión sobre valoraciones tech y múltiplos' : alcista ? 'Tipos favorables para tech — múltiplos soportados' : 'Tipos en zona neutral' });
      }
      if (sofr && fedfunds) {
        const estres = Math.abs(sofrSpread) > 0.5;
        score += estres ? -2 : 0;
        señales.push({ ind: 'SOFR vs Fed Funds (Repo)', val: 'Spread: ' + sofrSpread + '%', tend: Math.abs(sofrSpread) > 0.5 ? 'subiendo' : 'estable', señal: estres ? 'bajista_fuerte' : 'alcista', desc: estres ? '🚨 Estrés interbancario — spread repo elevado (similar a señales pre-2008)' : 'Mercado repo tranquilo — sin estrés interbancario' });
      }
      if (hySpread) {
        const bajista = hySpread.actual > 4;
        const muyBajista = hySpread.actual > 6;
        score += muyBajista ? -2 : bajista ? -1 : 1;
        señales.push({ ind: 'HY Credit Spread', val: hySpread.actual + '%', tend: hySpread.tendencia, señal: muyBajista ? 'bajista_fuerte' : bajista ? 'bajista' : 'alcista', desc: muyBajista ? '⚠️ Spread HY crítico — estrés crediticio serio, precede correcciones Nasdaq 2-4 semanas' : bajista ? 'HY en zona de vigilancia — crédito bajo presión' : 'HY contenido — mercado de crédito tranquilo' });
      }
      if (nfci) {
        const alcista = nfci.actual < 0;
        score += alcista ? 1 : -1;
        señales.push({ ind: 'NFCI (Condiciones Fin.)', val: nfci.actual, tend: nfci.tendencia, señal: alcista ? 'alcista' : 'bajista', desc: alcista ? 'Condiciones financieras acomodaticias (NFCI<0) — entorno favorable' : 'Condiciones financieras restrictivas (NFCI>0) — estrés sistémico' });
      }
      // Curva de tipos — sección especial
      if (t10y3m) {
        const muyInvertida = t10y3m.actual < -0.5;
        const invertida = t10y3m.actual < 0;
        score += muyInvertida ? -2 : invertida ? -1 : 0.5;
        señales.push({ ind: 'Curva 10Y-3M (Fed Cleveland)', val: t10y3m.actual + '%', tend: t10y3m.tendencia, señal: muyInvertida ? 'bajista_fuerte' : invertida ? 'bajista' : 'alcista', desc: muyInvertida ? '🚨 Curva 10Y-3M muy invertida — predictor recesión alta fiabilidad histórica' : invertida ? '⚠️ Curva 10Y-3M invertida — señal recesión moderada' : 'Curva 10Y-3M normal — sin señal recesión' });
      }
      if (t10y2y) {
        const invertida = t10y2y.actual < 0;
        score += invertida ? -0.5 : 0.5;
        señales.push({ ind: 'Curva 10Y-2Y', val: t10y2y.actual + '%', tend: t10y2y.tendencia, señal: invertida ? 'bajista' : 'alcista', desc: invertida ? 'Curva 10Y-2Y invertida — mercado anticipa bajadas de tipos' : 'Curva 10Y-2Y normal — expectativas de tipos moderadas' });
      }
      if (t5y5y) {
        señales.push({ ind: 'Expectativas largo plazo (5Y5Y)', val: t5y5y.actual + '%', tend: t5y5y.tendencia, señal: t5y5y.actual > 3 ? 'bajista' : t5y5y.actual < 2 ? 'alcista' : 'neutro', desc: t5y5y.actual > 3 ? 'Expectativas inflación largo plazo elevadas — presión estructural tipos' : 'Expectativas inflación ancladas — favorece múltiplos tech' });
      }

      return { score: parseFloat(score.toFixed(1)), señales, estado: score >= 2 ? 'favorable' : score <= -2 ? 'restrictivo' : 'neutro' };
    };

    const fredInterpretacion = interpretarFred(walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y, sofrSpread);

    resultado.fred = {
      walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y,
      sofrSpread, estadoCurva,
      score: fredInterpretacion.score,
      estado: fredInterpretacion.estado,
      señales: fredInterpretacion.señales
    };
  } catch(e) { resultado.fred = null; }

  // CONTEXTO SEMANAL — mismos cálculos pero en timeframe semanal
  try {
    const ndxW = await fetchYahoo('^NDX', '2y');
    if (ndxW && ndxW.closes.length >= 10) {
      // Convertir datos diarios a semanales (agrupar por semana)
      const toWeekly = (arr) => {
        const weeks = [];
        for (let i = 0; i < arr.length; i += 5) {
          const slice = arr.slice(i, i+5).filter(v => v);
          if (slice.length > 0) weeks.push(slice[slice.length-1]);
        }
        return weeks;
      };
      const wCloses = toWeekly(ndxW.closes);
      const wHighs  = toWeekly(ndxW.highs);
      const wLows   = toWeekly(ndxW.lows);
      const wn = wCloses.length;
      const wPrecio = wCloses[wn-1];

      // EMAs semanales
      const calcEMAw = (arr, p) => {
        if (arr.length < p) return null;
        const k = 2/(p+1);
        let ema = arr.slice(0,p).reduce((a,b)=>a+b,0)/p;
        for (let i=p; i<arr.length; i++) ema = arr[i]*k + ema*(1-k);
        return parseFloat(ema.toFixed(2));
      };
      const wEma20  = calcEMAw(wCloses, 20);
      const wEma50  = calcEMAw(wCloses, 50);
      const wSma200 = wCloses.length >= 200 ? parseFloat((wCloses.slice(-200).reduce((a,b)=>a+b,0)/200).toFixed(2)) : null;

      // RSI semanal
      const calcRSIw = (arr, p=14) => {
        if (arr.length < p+1) return null;
        let g=0, l=0;
        for (let i=arr.length-p; i<arr.length; i++) {
          const d = arr[i]-arr[i-1];
          if (d>0) g+=d; else l-=d;
        }
        const ag=g/p, al=l/p;
        return al===0 ? 100 : parseFloat((100-100/(1+ag/al)).toFixed(2));
      };
      const wRsi = calcRSIw(wCloses);

      // MACD semanal
      const calcEMAarr = (arr, p) => {
        if (arr.length < p) return null;
        const k = 2/(p+1);
        let ema = arr.slice(0,p).reduce((a,b)=>a+b,0)/p;
        for (let i=p; i<arr.length; i++) ema = arr[i]*k + ema*(1-k);
        return ema;
      };
      const wMacdLine = calcEMAarr(wCloses,12) && calcEMAarr(wCloses,26)
        ? parseFloat((calcEMAarr(wCloses,12) - calcEMAarr(wCloses,26)).toFixed(2)) : null;

      // Vela semanal actual
      const semanaAlcista = wCloses[wn-1] > wCloses[wn-2];
      const rangeSemana = wHighs[wn-1] - wLows[wn-1];
      const rangeMedia = wHighs.slice(-10).map((h,i)=>h-wLows[wn-10+i]).reduce((a,b)=>a+b,0)/10;
      const semanaExpansion = rangeSemana > rangeMedia * 1.3;

      // Máx/mín semana anterior
      const maxSemAnt = wHighs[wn-2];
      const minSemAnt = wLows[wn-2];

      // Tendencia semanal
      let tendenciaSemanal = 'lateral';
      if (wEma20 && wEma50) {
        if (wEma20 > wEma50 && wPrecio > wEma20) tendenciaSemanal = 'alcista_fuerte';
        else if (wEma20 > wEma50) tendenciaSemanal = 'alcista';
        else if (wEma20 < wEma50 && wPrecio < wEma20) tendenciaSemanal = 'bajista_fuerte';
        else tendenciaSemanal = 'bajista';
      }

      resultado.semanal = {
        precio: parseFloat(wPrecio.toFixed(2)),
        ema20: wEma20,
        ema50: wEma50,
        sma200: wSma200,
        rsi: wRsi,
        macd: wMacdLine,
        tendencia: tendenciaSemanal,
        vela: {
          alcista: semanaAlcista,
          expansion: semanaExpansion,
          rango: parseFloat(rangeSemana.toFixed(2))
        },
        niveles: {
          maxSemAnt: parseFloat(maxSemAnt.toFixed(2)),
          minSemAnt: parseFloat(minSemAnt.toFixed(2))
        },
        distEma20:  wEma20  ? parseFloat(((wPrecio-wEma20)/wEma20*100).toFixed(2))  : null,
        distEma50:  wEma50  ? parseFloat(((wPrecio-wEma50)/wEma50*100).toFixed(2))  : null,
        distSma200: wSma200 ? parseFloat(((wPrecio-wSma200)/wSma200*100).toFixed(2)) : null,
      };
    }
  } catch(e) { resultado.semanal = null; }

  // DETECTORES DE GIRO — 4 indicadores automáticos
  try {
    const ndxGiro = await fetchYahoo('^NDX', '6mo');
    if (ndxGiro && ndxGiro.closes.length >= 20) {
      const closes = ndxGiro.closes;
      const highs  = ndxGiro.highs;
      const lows   = ndxGiro.lows;
      const n = closes.length;
      const precio = closes[n-1];

      // ── 1. DIVERGENCIAS RSI con confirmación múltiple ──
      const calcRSIArr = (arr, period=14) => {
        const rsis = [];
        for (let i = period; i <= arr.length; i++) {
          let gains=0, losses=0;
          for (let j = i-period; j < i; j++) {
            const d = arr[j] - (j>0 ? arr[j-1] : arr[j]);
            if (d>0) gains+=d; else losses-=d;
          }
          const ag=gains/period, al=losses/period;
          rsis.push(al===0 ? 100 : parseFloat((100-100/(1+ag/al)).toFixed(2)));
        }
        return rsis;
      };
      const rsiArr = calcRSIArr(closes);
      const rsiN = rsiArr.length;

      // Detectar divergencia base
      let divAlcista = false, divBajista = false;
      for (let i = 5; i < Math.min(20, rsiN); i++) {
        const precioActual = closes[n-1], precioAnterior = closes[n-1-i];
        const rsiActual = rsiArr[rsiN-1], rsiAnterior = rsiArr[rsiN-1-i];
        if (precioActual < precioAnterior && rsiActual > rsiAnterior && rsiActual < 45) divAlcista = true;
        if (precioActual > precioAnterior && rsiActual < rsiAnterior && rsiActual > 60) divBajista = true;
      }

      // ── CONFIRMADORES DE DIVERGENCIA (para llegar al 80% fiabilidad) ──
      // Confirmador 1: Volumen decreciente en últimas 5 velas
      let volDecreciente = false;
      if (ndxGiro.volumes && ndxGiro.volumes.length >= 10) {
        const volReciente = ndxGiro.volumes.slice(-5).filter(v=>v).reduce((a,b)=>a+b,0)/5;
        const volAnterior = ndxGiro.volumes.slice(-10,-5).filter(v=>v).reduce((a,b)=>a+b,0)/5;
        volDecreciente = volReciente < volAnterior * 0.85;
      }

      // Confirmador 2: VIX subiendo mientras precio sube (trampa)
      const trampaVix = resultado.gex?.trampa || false;

      // Confirmador 3: AccDis divergiendo (bajando mientras precio sube)
      const accdisDiv = resultado.tecnicos?.accdis?.trend === 'bajando' && closes[n-1] > closes[n-6];

      // Calcular fiabilidad de la divergencia
      const confirmadoresBajistas = [volDecreciente, trampaVix, accdisDiv].filter(Boolean).length;
      const confirmadoresAlcistas = [!volDecreciente, !trampaVix].filter(Boolean).length;

      const divFiabilidad = divBajista
        ? (confirmadoresBajistas >= 2 ? 'alta' : confirmadoresBajistas >= 1 ? 'media' : 'baja')
        : divAlcista
        ? (confirmadoresAlcistas >= 2 ? 'alta' : 'media')
        : 'sin_divergencia';

      // ── 2. BANDAS DE BOLLINGER ──
      const period = 20;
      const sma20 = closes.slice(-period).reduce((a,b)=>a+b,0)/period;
      const variance = closes.slice(-period).reduce((s,v)=>s+Math.pow(v-sma20,2),0)/period;
      const std = Math.sqrt(variance);
      const bbUpper = parseFloat((sma20 + 2*std).toFixed(2));
      const bbLower = parseFloat((sma20 - 2*std).toFixed(2));
      const bbWidth = parseFloat(((bbUpper-bbLower)/sma20*100).toFixed(2));
      const bbPos   = parseFloat(((precio-bbLower)/(bbUpper-bbLower)*100).toFixed(1));
      let bbSeñal = 'neutro';
      if (precio >= bbUpper * 0.99) bbSeñal = 'techo_posible';
      else if (precio <= bbLower * 1.01) bbSeñal = 'suelo_posible';

      // ── 3. RATIO VIX/VXN ──
      const vixV = resultado.vix?.v;
      const vxnV = resultado.vxn?.v;
      let vixVxnRatio = null, vixVxnSeñal = 'normal';
      if (vixV && vxnV) {
        vixVxnRatio = parseFloat((vxnV/vixV).toFixed(2));
        if (vixVxnRatio > 1.4) vixVxnSeñal = 'estres_tech_extremo';
        else if (vixVxnRatio > 1.25) vixVxnSeñal = 'estres_tech_alto';
        else if (vixVxnRatio < 0.9) vixVxnSeñal = 'tech_calma_relativa';
      }

      // ── 4. DÍAS CONSECUTIVOS EN MISMA DIRECCIÓN ──
      let diasConsecutivos = 0, direccion = 'lateral';
      for (let i = n-1; i > n-15; i--) {
        const sube = closes[i] > closes[i-1];
        const baja = closes[i] < closes[i-1];
        if (i === n-1) { direccion = sube ? 'subiendo' : baja ? 'bajando' : 'lateral'; }
        if (direccion === 'subiendo' && sube) diasConsecutivos++;
        else if (direccion === 'bajando' && baja) diasConsecutivos++;
        else break;
      }
      let diasSeñal = 'normal';
      if (diasConsecutivos >= 7 && direccion === 'subiendo') diasSeñal = 'agotamiento_alcista';
      else if (diasConsecutivos >= 5 && direccion === 'bajando') diasSeñal = 'rebote_probable';
      else if (diasConsecutivos >= 5 && direccion === 'subiendo') diasSeñal = 'vigilar_techo';

      resultado.giro = {
        divergencias: {
          alcista: divAlcista,
          bajista: divBajista,
          fiabilidad: divFiabilidad,
          confirmadores: confirmadoresBajistas,
          volDecreciente, trampaVix, accdisDiv,
          señal: divAlcista ? 'suelo_posible' : divBajista ? 'techo_posible' : 'sin_divergencia'
        },
        bollinger: {
          upper: bbUpper, lower: bbLower, sma20: parseFloat(sma20.toFixed(2)),
          width: bbWidth, posicion: bbPos, señal: bbSeñal
        },
        vixVxn: {
          ratio: vixVxnRatio, señal: vixVxnSeñal,
          descripcion: vixVxnSeñal === 'estres_tech_extremo' ? 'Estrés extremo en tech — giro bajista posible' :
                       vixVxnSeñal === 'estres_tech_alto' ? 'Estrés elevado en Nasdaq vs S&P' :
                       vixVxnSeñal === 'tech_calma_relativa' ? 'Nasdaq más tranquilo que el mercado general' : 'Normal'
        },
        diasConsecutivos: {
          dias: diasConsecutivos, direccion,
          señal: diasSeñal,
          descripcion: diasSeñal === 'agotamiento_alcista' ? diasConsecutivos + ' días subiendo — agotamiento alcista probable' :
                       diasSeñal === 'rebote_probable' ? diasConsecutivos + ' días bajando — rebote técnico probable' :
                       diasSeñal === 'vigilar_techo' ? diasConsecutivos + ' días subiendo — vigilar señales de techo' :
                       diasConsecutivos + ' días ' + direccion + ' — sin señal extrema'
        },
        señalGlobal: (divBajista || bbSeñal==='techo_posible' || diasSeñal==='agotamiento_alcista') ? 'techo' :
                     (divAlcista || bbSeñal==='suelo_posible' || diasSeñal==='rebote_probable') ? 'suelo' : 'neutro'
      };
    }
  } catch(e) { resultado.giro = null; }

  // GEX aproximado — calculado desde VIX, VXN y Put/Call
  // No es el GEX real pero es una estimación útil
  try {
    const vix = resultado.vix?.v;
    const vxn = resultado.vxn?.v;
    const vixChg = resultado.vix?.chg;
    const nqChg = resultado.nq?.chg;

    if (vix && vxn) {
      // Lógica de aproximación GEX:
      // VIX < 16 + estable = gamma positiva alta
      // VIX 16-20 = gamma positiva moderada
      // VIX 20-25 = gamma neutra/transición
      // VIX > 25 = gamma negativa
      // VIX subiendo MIENTRAS precio sube = señal trampa (distribución)

      let gexEstado, gexValor, gexDescripcion, gexAlerta;

      const trampaInstitucional = vixChg > 2 && nqChg > 0.3;

      if (vix < 16) {
        gexEstado = 'positiva_alta';
        gexValor = 3;
        gexDescripcion = 'Dealers estabilizando fuerte. Mercado en rango, reversión a la media.';
      } else if (vix < 20) {
        gexEstado = 'positiva';
        gexValor = 2;
        gexDescripcion = 'Dealers comprando caídas y vendiendo rallies. Mercado sostenido.';
      } else if (vix < 25) {
        gexEstado = 'neutra';
        gexValor = 0;
        gexDescripcion = 'Transición. Dealers en equilibrio. Mayor incertidumbre de dirección.';
      } else if (vix < 30) {
        gexEstado = 'negativa';
        gexValor = -2;
        gexDescripcion = 'Dealers amplificando movimientos. Posibles tendencias violentas.';
      } else {
        gexEstado = 'negativa_extrema';
        gexValor = -3;
        gexDescripcion = 'Dealers sin control. Movimientos explosivos. Alto riesgo.';
      }

      // Ajuste por VXN (Nasdaq específico)
      if (vxn > vix * 1.3) {
        gexValor -= 1;
        gexDescripcion += ' VXN elevado vs VIX indica estrés específico en tech.';
      }

      // Alerta trampa institucional
      if (trampaInstitucional) {
        gexAlerta = 'TRAMPA: Precio sube pero VIX también sube — posible distribución institucional';
      }

      resultado.gex = {
        estado: gexEstado,
        valor: gexValor,
        descripcion: gexDescripcion,
        alerta: gexAlerta || null,
        trampa: trampaInstitucional,
        vixUsado: vix,
        vxnUsado: vxn
      };
    }
  } catch(e) { resultado.gex = null; }

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
