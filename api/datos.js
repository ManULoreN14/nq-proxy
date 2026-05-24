// api/datos.js — Proxy datos mercado + indicadores técnicos automáticos
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET');
  res.setHeader('Cache-Control', 's-maxage=300');

  // ── Helpers de cálculo técnico ──────────────────────────────
  function calcRSI(closes, period = 14) {
    // RSI de Wilder (smoothed) — igual que TradingView
    if (closes.length < period * 2) return null;
    // Primera media: simple sobre primeros 'period' cambios
    let avgGain = 0, avgLoss = 0;
    for (let i = 1; i <= period; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff >= 0) avgGain += diff; else avgLoss -= diff;
    }
    avgGain /= period;
    avgLoss /= period;
    // Suavizado exponencial de Wilder para el resto
    for (let i = period + 1; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      const gain = diff >= 0 ? diff : 0;
      const loss = diff < 0 ? -diff : 0;
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
    }
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
    const rawClose  = quote?.close  ?? [];
    const rawHigh   = quote?.high   ?? [];
    const rawLow    = quote?.low    ?? [];
    const rawVolume = quote?.volume ?? [];

    // CRÍTICO: alinear por índice común — nunca filtrar arrays individualmente
    // Si cualquier campo es null en un día, excluir ese día de TODOS los arrays
    const closes = [], highs = [], lows = [], volumes = [];
    for (let i = 0; i < rawClose.length; i++) {
      if (rawClose[i] != null && rawHigh[i] != null && rawLow[i] != null) {
        closes.push(rawClose[i]);
        highs.push(rawHigh[i]);
        lows.push(rawLow[i]);
        volumes.push(rawVolume[i] ?? 0);
      }
    }
    return { closes, highs, lows, volumes };
  }

  const resultado = {};

  // ── Fetch paralelo de todos los datos independientes ────────
  // Lanzar todas las peticiones a la vez para minimizar latencia
  const [
    rawVix, rawVxn, rawNq, rawUs10, rawDxy,
    rawNdx, rawNdx6mo, rawNdxW, rawNdxFib
  ] = await Promise.allSettled([
    fetchYahoo('^VIX',    '5d'),
    fetchYahoo('^VXN',    '5d'),
    fetchYahoo('NQ=F',    '5d'),
    fetchYahoo('^TNX',    '5d'),
    fetchYahoo('DX-Y.NYB','5d'),
    fetchYahoo('^NDX',    '1y'),
    fetchYahoo('^NDX',    '6mo'),
    fetchYahoo('^NDX',    '2y'),
    fetchYahoo('^NDX',    '1y')   // para fibonacci/liquidez (reutiliza rawNdx)
  ]);

  const getVal = (settled) => settled.status === 'fulfilled' ? settled.value : null;

  // Datos básicos desde fetch paralelo
  const basicMap = [
    ['vix', getVal(rawVix)],
    ['vxn', getVal(rawVxn)],
    ['nq',  getVal(rawNq)],
    ['us10',getVal(rawUs10)],
    ['dxy', getVal(rawDxy)]
  ];
  for (const [key, d] of basicMap) {
    try {
      if (!d || d.closes.length < 2) { resultado[key] = null; continue; }
      const last = d.closes[d.closes.length - 1];
      const prev = d.closes[d.closes.length - 2];
      resultado[key] = {
        v: parseFloat(last.toFixed(2)),
        chg: parseFloat(((last - prev) / prev * 100).toFixed(2))
      };
    } catch { resultado[key] = null; }
  }

  // ── Indicadores técnicos del NDX ────────────────────────────
  try {
    const ndx = getVal(rawNdx);
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

  // ── Lanzar en paralelo: FRED + MaxPain + AV + NewsAPI + GDELT + Empresarial ──
  // Todas son independientes entre sí — no hay razón para ejecutarlas en serie
  await Promise.allSettled([
    (async () => {
      // MAX PAIN
      try {
        const expUrl = 'https://query1.finance.yahoo.com/v7/finance/options/QQQ';
        const expResp = await fetch(expUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
        const expData = await expResp.json();
        const expirations = expData?.optionChain?.result?.[0]?.expirationDates || [];
        if (expirations.length > 0) {
          const nextExp = expirations[0];
          const optUrl = `https://query1.finance.yahoo.com/v7/finance/options/QQQ?date=${nextExp}`;
          const optResp = await fetch(optUrl, { headers: { 'User-Agent': 'Mozilla/5.0' } });
          const optData = await optResp.json();
          const chain = optData?.optionChain?.result?.[0];
          if (chain) {
            const calls = chain.options?.[0]?.calls || [];
            const puts  = chain.options?.[0]?.puts  || [];
            const precio = chain.quote?.regularMarketPrice;
            const strikes = [...new Set([...calls.map(c=>c.strike),...puts.map(p=>p.strike)])].sort((a,b)=>a-b);
            let minDolor = Infinity, maxPain = precio;
            for (const strike of strikes) {
              let dolor = 0;
              for (const call of calls) if (call.strike < strike) dolor += (strike - call.strike) * (call.openInterest||0);
              for (const put  of puts)  if (put.strike  > strike) dolor += (put.strike  - strike) * (put.openInterest||0);
              if (dolor < minDolor) { minDolor = dolor; maxPain = strike; }
            }
            const distPct = parseFloat(((maxPain - precio) / precio * 100).toFixed(2));
            resultado.maxpain = {
              valor: maxPain, precio: parseFloat(precio.toFixed(2)), distPct,
              expiracion: new Date(nextExp * 1000).toISOString().slice(0,10),
              señal: distPct > 3 ? 'acumulacion' : distPct < -3 ? 'distribucion' : 'neutro',
              descripcion: distPct > 3 ? 'Precio bajo Max Pain — dealers incentivados a subir' : distPct < -3 ? 'Precio sobre Max Pain — dealers incentivados a bajar' : 'Precio cerca del Max Pain — dealers neutrales'
            };
          }
        }
      } catch(e) { resultado.maxpain = null; }
    })(),

    (async () => {
      // ALPHA VANTAGE
      try {
        const AV_KEY = 'MBL9WFVPPXOK7ZU8';
        const avUrl = `https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=technology,financial_markets,economy_fiscal&sort=LATEST&limit=10&apikey=${AV_KEY}`;
        const avResp = await fetch(avUrl);
        const avData = await avResp.json();
        let sentimentScore = null, sentimentDesc = null;
        const noticias = [];
        if (avData?.feed) {
          const scores = avData.feed.filter(n=>n.overall_sentiment_score!==undefined).map(n=>parseFloat(n.overall_sentiment_score));
          if (scores.length > 0) {
            const avg = scores.reduce((a,b)=>a+b,0)/scores.length;
            sentimentScore = parseFloat(((avg+1)*50).toFixed(1));
            sentimentDesc = avg>0.25?'Sentimiento muy alcista — posible complacencia':avg>0.05?'Sentimiento alcista moderado':avg<-0.25?'Sentimiento muy bajista — posible capitulación':avg<-0.05?'Sentimiento bajista moderado':'Sentimiento neutro';
          }
          avData.feed.slice(0,8).forEach(n => noticias.push({ titulo:n.title, fuente:n.source, fecha:n.time_published?.slice(0,10), resumen:n.summary?.slice(0,150), sentiment:n.overall_sentiment_label, sentimentScore:n.overall_sentiment_score }));
        }
        if (noticias.length > 0 || sentimentScore !== null) resultado.finnhub = { noticias, sentimentScore, sentimentDesc, fuente:'alphavantage' };
      } catch(e) { resultado.finnhub = null; }
    })(),

    (async () => {
      // NEWSAPI
      try {
        const NEWS_KEY = '08b850a8842a47568e83e4433a6c3e7d';
        const noticias = [];
        for (const q of ['Federal Reserve interest rates', 'Nasdaq tech stocks']) {
          try {
            const url = `https://newsapi.org/v2/everything?q=${encodeURIComponent(q)}&language=en&sortBy=publishedAt&pageSize=3&apiKey=${NEWS_KEY}`;
            const r = await fetch(url);
            const d = await r.json();
            if (d.status==='ok' && d.articles) noticias.push(...d.articles.map(a=>({ titulo:a.title, fuente:a.source?.name, fecha:a.publishedAt?.slice(0,10), descripcion:a.description?.slice(0,150) })));
          } catch {}
        }
        if (noticias.length > 0) resultado.noticias = noticias.slice(0,6);
      } catch(e) { resultado.noticias = null; }
    })(),

    (async () => {
      // EMPRESARIAL
      try {
        const top10 = ['NVDA','AAPL','MSFT','AMZN','META','AVGO'];
        let qqqPER = null;
        try {
          const qi = await fetch('https://query1.finance.yahoo.com/v10/finance/quoteSummary/QQQ?modules=summaryDetail', { headers:{'User-Agent':'Mozilla/5.0'} });
          const qd = await qi.json();
          const pe = qd?.quoteSummary?.result?.[0]?.summaryDetail?.trailingPE?.raw;
          if (pe) qqqPER = parseFloat(pe.toFixed(1));
        } catch {}
        const earningsProximos = [];
        const hoy = new Date(), en7d = new Date(hoy.getTime()+7*86400000);
        await Promise.allSettled(top10.map(async sym => {
          try {
            const r = await fetch(`https://query1.finance.yahoo.com/v10/finance/quoteSummary/${sym}?modules=calendarEvents,financialData`, { headers:{'User-Agent':'Mozilla/5.0'} });
            const d = await r.json();
            const res = d?.quoteSummary?.result?.[0];
            const earDate = res?.calendarEvents?.earnings?.earningsDate?.[0]?.raw;
            if (earDate) {
              const fecha = new Date(earDate*1000);
              earningsProximos.push({ simbolo:sym, fecha:fecha.toISOString().slice(0,10), enProximos7dias:fecha>=hoy&&fecha<=en7d, recomendacion:res?.financialData?.recommendationKey, crecimientoIngresos:res?.financialData?.revenueGrowth?.raw?parseFloat((res.financialData.revenueGrowth.raw*100).toFixed(1)):null });
            }
          } catch {}
        }));
        const val = qqqPER>35?'cara':qqqPER>28?'elevada':qqqPER<20?'barata':'normal';
        resultado.empresarial = { qqqPER, valoracionQQQ:val, valoracionDesc:qqqPER?`PER QQQ en ${qqqPER}x — valoración ${val}`:'PER no disponible', earningsProximos:earningsProximos.sort((a,b)=>new Date(a.fecha)-new Date(b.fecha)), earningsSemana:earningsProximos.filter(e=>e.enProximos7dias) };
      } catch(e) { resultado.empresarial = null; }
    })()
  ]);

  // RADAR 2-5 DÍAS — datos automáticos
  try {
    const radarData = {};

    // 1. VIX TERM STRUCTURE
    try {
      const vixSpot = resultado.vix?.v;
      const vix3mData = await fetchYahoo('^VIX3M', '5d');
      if (vixSpot && vix3mData?.closes?.length > 0) {
        const vix3m = vix3mData.closes[vix3mData.closes.length - 1];
        const spread = parseFloat((vix3m - vixSpot).toFixed(2));
        radarData.vixTermStructure = {
          vixSpot, vix3m: parseFloat(vix3m.toFixed(2)), spread,
          estructura: spread > 2 ? 'contango_fuerte' : spread > 0 ? 'contango' : spread > -2 ? 'backwardation' : 'backwardation_fuerte',
          señal: spread > 0 ? 'alcista' : 'bajista',
          descripcion: spread > 2 ? 'Contango fuerte — complacencia, corrección posible 3-7d' :
                       spread > 0 ? 'Contango normal — sin estrés inmediato' :
                       spread > -2 ? 'Backwardation leve — estrés corto plazo, rebote posible' :
                       'Backwardation fuerte — pánico, rebote probable 2-5d'
        };
      }
    } catch {}

    // 2. ETF FLOWS QQQ — aproximación via volumen relativo
    try {
      const qqqVol = await fetchYahoo('QQQ', '20d');
      if (qqqVol?.volumes?.length >= 10) {
        const vols = qqqVol.volumes;
        const cls = qqqVol.closes;
        const n = vols.length;
        const volReciente = vols.slice(-5).reduce((a,b)=>a+b,0)/5;
        const volMedia = vols.reduce((a,b)=>a+b,0)/n;
        const retorno5d = parseFloat(((cls[n-1]-cls[n-6])/cls[n-6]*100).toFixed(2));
        const volRatio = parseFloat((volReciente/volMedia).toFixed(2));
        const flujo = retorno5d > 0 && volRatio > 1.1 ? 'entradas' : retorno5d < 0 && volRatio > 1.1 ? 'salidas' : 'neutro';
        radarData.etfFlows = {
          volRatio, retorno5d, flujoEstimado: flujo,
          señal: flujo === 'entradas' ? 'alcista' : flujo === 'salidas' ? 'bajista' : 'neutro',
          descripcion: flujo === 'entradas' ? `Vol ${((volRatio-1)*100).toFixed(0)}% sobre media con precio subiendo — flujo positivo` :
                       flujo === 'salidas' ? `Vol ${((volRatio-1)*100).toFixed(0)}% sobre media con precio bajando — posibles salidas` :
                       'Volumen normal — sin señal de flujo claro'
        };
      }
    } catch {}

    // 3. OI STRIKES desde Max Pain ya calculado
    if (resultado.maxpain) {
      const mp = resultado.maxpain;
      radarData.oiStrikes = {
        maxPain: mp.valor, precio: mp.precio, distPct: mp.distPct,
        señal: mp.señal,
        resistenciaEstimada: parseFloat((mp.valor * 1.015).toFixed(2)),
        soporteEstimado: parseFloat((mp.valor * 0.985).toFixed(2)),
        descripcion: mp.distPct > 5 ? 'Precio muy sobre Max Pain — gravedad opciones presiona hacia abajo en vencimiento' :
                     mp.distPct < -5 ? 'Precio muy bajo Max Pain — gravedad opciones impulsa hacia arriba' :
                     'Precio cerca de Max Pain — zona de equilibrio'
      };
    }

    // 4. MOMENTUM ROC 5d
    try {
      const ndxRoc = await fetchYahoo('^NDX', '10d');
      if (ndxRoc?.closes?.length >= 6) {
        const cls = ndxRoc.closes;
        const n = cls.length;
        const roc5d = parseFloat(((cls[n-1]-cls[n-6])/cls[n-6]*100).toFixed(2));
        const roc3d = parseFloat(((cls[n-1]-cls[n-4])/cls[n-4]*100).toFixed(2));
        radarData.momentum = {
          roc5d, roc3d,
          señal: roc5d > 4 ? 'sobreextendido_alcista' : roc5d < -4 ? 'sobreextendido_bajista' : roc5d > 1 ? 'alcista' : roc5d < -1 ? 'bajista' : 'neutro',
          descripcion: Math.abs(roc5d) > 4 ? `${roc5d}% en 5d — sobreextensión, mean reversion probable 2-5d` :
                       `${roc5d}% en 5d — momentum ${roc5d > 0 ? 'positivo' : 'negativo'}`
        };
      }
    } catch {}

    // Score radar
    let rs = 0;
    if (radarData.vixTermStructure) rs += radarData.vixTermStructure.señal === 'alcista' ? 2 : -2;
    if (radarData.etfFlows) rs += radarData.etfFlows.señal === 'alcista' ? 2 : radarData.etfFlows.señal === 'bajista' ? -2 : 0;
    if (radarData.oiStrikes) rs += radarData.oiStrikes.distPct > 3 ? -1 : radarData.oiStrikes.distPct < -3 ? 1 : 0;
    if (radarData.momentum) rs += radarData.momentum.señal.includes('sobreextendido') ? (radarData.momentum.roc5d > 0 ? -2 : 2) : radarData.momentum.roc5d > 0 ? 1 : -1;

    radarData.score = parseFloat(rs.toFixed(1));
    radarData.estado = rs >= 3 ? 'alcista' : rs <= -3 ? 'bajista' : 'neutro';
    radarData.descripcion = rs >= 3 ? 'Condiciones favorables para subida en 2-5 días' :
                            rs <= -3 ? 'Riesgo elevado de corrección en 2-5 días' :
                            'Sin señal clara para 2-5 días — cautela';
    resultado.radar = radarData;
  } catch(e) { resultado.radar = null; }

  // SCORING UNIFICADO — combina técnico + macro + sentimiento + geopolítico
  // Se calcula al final cuando todos los datos están disponibles
  try {
    let scoreTecnico = 0, scoreMacro = 0, scoreSentimiento = 0;
    let pesoTec = 0, pesoMac = 0, pesoSent = 0;

    // ── TÉCNICO (40%) ──
    if (resultado.tecnicos) {
      const t = resultado.tecnicos;
      if (t.rsi) {
        if (t.rsi.valor >= 45 && t.rsi.valor <= 65) scoreTecnico += 2;
        else if (t.rsi.valor > 70) scoreTecnico -= 1;
        else if (t.rsi.valor < 30) scoreTecnico += 1;
      }
      if (t.ema50?.cruceEmas === 'alcista') scoreTecnico += 2;
      else scoreTecnico -= 1;
      if (t.sma200?.distanciaPct > 0) scoreTecnico += 1;
      else scoreTecnico -= 2;
      if (t.macd?.histogram > 0) scoreTecnico += 1;
      else scoreTecnico -= 1;
      pesoTec = 1;
    }

    // ── MACRO FRED (30%) ──
    if (resultado.fred) {
      scoreMacro = resultado.fred.score;
      pesoMac = 1;
    }

    // ── SENTIMIENTO + NOTICIAS (30%) ──
    let sentScore = 0;
    if (resultado.finnhub?.sentimentScore) {
      const s = resultado.finnhub.sentimentScore;
      sentScore += s > 65 ? -1 : s > 55 ? 1 : s < 35 ? -1 : s < 45 ? -0.5 : 0.5;
    }
    if (resultado.vix?.v) {
      sentScore += resultado.vix.v < 16 ? 2 : resultado.vix.v < 20 ? 1 : resultado.vix.v < 25 ? 0 : resultado.vix.v < 30 ? -1 : -2;
    }
    if (resultado.gex?.trampa) sentScore -= 2;
    pesoSent = 1;

    if (pesoTec + pesoMac + pesoSent > 0) {
      // Score normalizado -10 a +10
      const scoreNorm = (
        (pesoTec > 0 ? (scoreTecnico / 7) * 0.4 : 0) +
        (pesoMac > 0 ? (scoreMacro / 8) * 0.3 : 0) +
        (pesoSent > 0 ? (sentScore / 4) * 0.3 : 0)
      ) * 10;

      const scoreF = parseFloat(Math.max(-10, Math.min(10, scoreNorm)).toFixed(1));
      resultado.scoreUnificado = {
        score: scoreF,
        componentes: {
          tecnico: parseFloat(scoreTecnico.toFixed(1)),
          macro: parseFloat(scoreMacro.toFixed(1)),
          sentimiento: parseFloat(sentScore.toFixed(1))
        },
        estado: scoreF >= 3 ? 'alcista' : scoreF <= -3 ? 'bajista' : 'neutro',
        descripcion: scoreF >= 5 ? 'Entorno muy favorable para el Nasdaq' :
                     scoreF >= 3 ? 'Entorno favorable — sesgo alcista' :
                     scoreF >= 0 ? 'Entorno neutro con ligero sesgo alcista' :
                     scoreF >= -3 ? 'Entorno neutral con riesgo creciente' :
                     scoreF >= -5 ? 'Entorno desfavorable — cautela' :
                     'Entorno muy adverso — proteger capital'
      };
    }
  } catch(e) { resultado.scoreUnificado = null; }



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

    const [walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y, t5yie, t10yie, ff2y] = await Promise.all([
      fredFetch('WALCL'),         // Balance Fed
      fredFetch('FEDFUNDS'),      // Fed Funds Rate
      fredFetch('BAMLH0A0HYM2'), // HY Credit Spread
      fredFetch('NFCI'),          // Condiciones financieras
      fredFetch('T10Y2Y'),        // Curva 10Y-2Y
      fredFetch('T10Y3M'),        // Curva 10Y-3M
      fredFetch('SOFR'),          // Tipo repo SOFR
      fredFetch('T5Y5Y'),         // Expectativas largo plazo
      fredFetch('T5YIE'),         // TIPS Breakeven 5Y — inflación implícita
      fredFetch('T10YIE'),        // TIPS Breakeven 10Y — inflación implícita largo plazo
      fredFetch('DFF')            // Fed Funds efectivo diario (más reciente que FEDFUNDS)
    ]);

    // Expectativas política monetaria Fed
    // El diferencial Bono2Y - Fed Funds descuenta lo que el mercado espera en 12 meses
    let fedExpectativas = null;
    try {
      const bono2y = await fetchYahoo('^IRX', '5d'); // T-Bill 3M como proxy
      const bono2yVal = bono2y?.closes?.[bono2y.closes.length-1];
      const ffVal = ff2y?.actual || fedfunds?.actual;
      if (bono2yVal && ffVal) {
        const diferencial = parseFloat((bono2yVal/10 - ffVal).toFixed(2));
        fedExpectativas = {
          diferencialBono2y: diferencial,
          descripcion: diferencial < -0.5 ? 'Mercado descuenta bajadas de tipos significativas en 12 meses' :
                       diferencial < 0 ? 'Mercado descuenta ligeras bajadas de tipos' :
                       diferencial > 0.5 ? 'Mercado descuenta subidas de tipos — presión alcista en yields' :
                       'Mercado no descuenta cambios significativos en tipos',
          sesgo: diferencial < -0.3 ? 'dovish' : diferencial > 0.3 ? 'hawkish' : 'neutro'
        };
      }
    } catch {}

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
        const alto = t5y5y.actual > 3;
        score += alto ? -1 : 0.5;
        señales.push({ ind: 'Expectativas largo plazo (5Y5Y)', val: t5y5y.actual + '%', tend: t5y5y.tendencia, señal: alto ? 'bajista' : 'alcista', desc: alto ? 'Expectativas inflación largo plazo elevadas — presión estructural en tipos y múltiplos tech' : 'Expectativas inflación ancladas — favorece múltiplos tech' });
      }
      if (t5yie) {
        const alta = t5yie.actual > 2.5;
        score += alta ? -0.5 : 0.5;
        señales.push({ ind: 'TIPS Breakeven 5Y (inflación implícita)', val: t5yie.actual + '%', tend: t5yie.tendencia, señal: alta ? 'bajista' : 'alcista', desc: alta ? 'Mercado descuenta inflación >2.5% a 5 años — Fed puede mantener tipos altos más tiempo' : 'Inflación implícita controlada — Fed puede ser más dovish' });
      }
      if (t10yie) {
        señales.push({ ind: 'TIPS Breakeven 10Y', val: t10yie.actual + '%', tend: t10yie.tendencia, señal: t10yie.actual > 2.5 ? 'bajista' : 'alcista', desc: 'Expectativas inflación largo plazo: ' + t10yie.actual + '% · ' + (t10yie.tendencia === 'subiendo' ? 'subiendo — presión en yields' : 'estable/bajando — favorable') });
      }

      return { score: parseFloat(score.toFixed(1)), señales, estado: score >= 3 ? 'favorable' : score <= -2 ? 'restrictivo' : 'neutro' };
    };

    const fredInterpretacion = interpretarFred(walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y, sofrSpread);

    resultado.fred = {
      walcl, fedfunds, hySpread, nfci, t10y2y, t10y3m, sofr, t5y5y,
      t5yie, t10yie, ff2y, fedExpectativas, sofrSpread, estadoCurva,
      score: fredInterpretacion.score,
      estado: fredInterpretacion.estado,
      señales: fredInterpretacion.señales
    };
  } catch(e) { resultado.fred = null; }





  // GDELT — Volumen y tono de noticias globales (sin API key, 100% gratuito)
  try {
    const gdeltTopics = [
      { tema: 'semiconductors', label: 'Semiconductores' },
      { tema: 'Federal Reserve interest rates', label: 'Fed / Tipos' },
      { tema: 'artificial intelligence', label: 'IA / Tech' },
      { tema: 'trade tariffs China', label: 'Aranceles / China' },
      { tema: 'inflation economy', label: 'Inflación' }
    ];

    const gdeltResultados = [];

    for (const topic of gdeltTopics) {
      try {
        // TimelineVol — volumen de noticias últimas 24h
        const volUrl = `https://api.gdeltproject.org/api/v2/doc/doc?query=${encodeURIComponent(topic.tema)}&mode=timelinevol&format=json&timespan=24h&smoothing=0`;
        const volResp = await fetch(volUrl);
        const volData = await volResp.json();

        // ToneChart — sentimiento
        const toneUrl = `https://api.gdeltproject.org/api/v2/doc/doc?query=${encodeURIComponent(topic.tema)}&mode=tonechart&format=json&timespan=24h`;
        const toneResp = await fetch(toneUrl);
        const toneData = await toneResp.json();

        // Extraer datos
        let volActual = 0, volAnterior = 0, tonoPromedio = 0;

        if (volData?.timeline?.[0]?.data?.length > 0) {
          const pts = volData.timeline[0].data;
          const n = pts.length;
          volActual = pts[n-1]?.value || 0;
          volAnterior = n > 4 ? pts.slice(-5,-1).reduce((a,b) => a + (b.value||0), 0) / 4 : volActual;
        }

        if (toneData?.timeline?.[0]?.data?.length > 0) {
          const pts = toneData.timeline[0].data;
          tonoPromedio = pts.slice(-6).reduce((a,b) => a + (b.value||0), 0) / Math.min(6, pts.length);
        }

        const volCambio = volAnterior > 0 ? ((volActual - volAnterior) / volAnterior * 100) : 0;

        gdeltResultados.push({
          tema: topic.label,
          volumen: parseFloat(volActual.toFixed(2)),
          volCambioPct: parseFloat(volCambio.toFixed(1)),
          tono: parseFloat(tonoPromedio.toFixed(2)),
          señal: tonoPromedio < -2 ? 'negativo' : tonoPromedio > 2 ? 'positivo' : 'neutro',
          alertaVol: Math.abs(volCambio) > 50, // pico de noticias = volatilidad
          desc: (Math.abs(volCambio) > 50 ? '⚡ Pico de noticias +' + volCambio.toFixed(0) + '% ' : '') +
                (tonoPromedio < -2 ? '🔴 Tono negativo (' + tonoPromedio.toFixed(1) + ')' :
                 tonoPromedio > 2 ? '🟢 Tono positivo (' + tonoPromedio.toFixed(1) + ')' :
                 '→ Tono neutro (' + tonoPromedio.toFixed(1) + ')')
        });
      } catch {}
    }

    if (gdeltResultados.length > 0) {
      // Score GDELT: tono negativo en semis/Fed = bajista
      const gdeltScore = gdeltResultados.reduce((acc, r) => {
        const pesoTema = r.tema.includes('Semi') ? 2 : r.tema.includes('Fed') ? 1.5 : 1;
        return acc + (r.señal === 'positivo' ? pesoTema : r.señal === 'negativo' ? -pesoTema : 0);
      }, 0);

      resultado.gdelt = {
        temas: gdeltResultados,
        score: parseFloat(gdeltScore.toFixed(1)),
        alertaVolatilidad: gdeltResultados.some(r => r.alertaVol),
        estado: gdeltScore > 2 ? 'positivo' : gdeltScore < -2 ? 'negativo' : 'neutro'
      };
    }
  } catch(e) { resultado.gdelt = null; }



  // CONTEXTO SEMANAL — mismos cálculos pero en timeframe semanal
  try {
    const ndxW = getVal(rawNdxW);
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
    const ndxGiro = getVal(rawNdx6mo);
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
    const ndxFib = getVal(rawNdx); // reutilizar el mismo fetch de 1y
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
