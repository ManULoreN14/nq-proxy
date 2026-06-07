#!/usr/bin/env python3
"""
gex_parser.py  v1.1
====================
Calcula GEX (Gamma Exposure) + Max Pain + Top OI strikes para QQQ
desde texto copiado del broker (formato Datashop / IBKR / ToS estilo).

INSTRUCCIONES:
  1. Ve al broker -> QQQ Options Chain -> Options Range = "All"
  2. Selecciona "All Expirations" (o el vencimiento mas cercano)
  3. Ctrl+A -> Ctrl+C
  4. Pega en:  C:\\Users\\m21lo\\nq-proxy\\opciones.txt
  5. Ejecuta:  python gex_parser.py opciones.txt 705.06

SALIDA: gex_manual.json (en la misma carpeta + nq-proxy + UNIFICADO)
  Contiene:
    - GEX Total, Gamma Flip Level
    - Max Pain por vencimiento
    - Top 5 calls OI (resistencias) y Top 5 puts OI (soportes)
    - resistencia_principal y soporte_principal (cerca del precio)
  Estos datos los lee actualizar_radar.py para auto-rellenar:
    * Panel "Derivados Avanzados" (GEX, Gamma Flip)
    * Panel "Open Interest por Strike - Paredes" (Radar 2-5D)
    * Panel "Paredes de Opciones - Max Pain - GEX"
"""

import re, sys, json
from pathlib import Path
from datetime import datetime

PRECIO_DEFAULT = 705.06

SKIP_EXACT = {
    'Calls','Puts','Strike','Last','Net','Bid','Ask','Vol','IV',
    'Delta','Gamma','Int','Options Chain','All Strike Prices','List',
    'All Options','In The Money','Near the Money','Calls and Puts',
    'Last Trade Date (EDT)','Contract Name','Change','% Change',
    'Volume','Open Interest','Implied Volatility',
}

def parse_num(s):
    try:
        return float(s.strip().replace('+','').replace(',','').replace(' ',''))
    except:
        return None

def is_date_line(s):
    return bool(re.match(
        r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\w+\s+\d{1,2}\s+\d{4}$', s.strip()
    ))

def is_strike_line(s):
    return bool(re.match(r'QQQ\s+[\d.]+$', s.strip()))

def should_skip(line):
    if line in SKIP_EXACT:
        return True
    if re.match(r'Total Records:\s*\d+', line):
        return True
    if re.match(r'Options analytics', line):
        return True
    if re.match(r'QQQ\d{6}[CP]\d+', line):
        return True
    return False

# ── Parser principal ──────────────────────────────────────────────────────
def parse_file(filepath):
    """
    Lee el archivo y extrae bloques {expiry, strikes, calls[], puts[]}.
    Cada opcion ocupa 9 lineas numericas: Last,Net,Bid,Ask,Vol,IV,Delta,Gamma,OI
    """
    text = Path(filepath).read_text(encoding='utf-8', errors='ignore')
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    blocks = []
    section   = None
    call_rows = []
    put_rows  = []
    strikes   = []
    expiry    = None
    nbuf      = []

    def flush():
        if expiry and strikes and call_rows:
            blocks.append({
                'expiry': expiry,
                'strikes': list(strikes),
                'calls':   list(call_rows),
                'puts':    list(put_rows),
            })

    for line in lines:
        if line == 'Calls':
            flush()
            section   = 'calls'
            call_rows, put_rows, strikes, expiry = [], [], [], None
            nbuf = []
            continue
        if line == 'Puts':
            section = 'puts'
            nbuf = []
            continue
        if should_skip(line):
            continue
        if is_date_line(line):
            expiry  = line
            strikes = []
            nbuf    = []
            continue
        if is_strike_line(line):
            val = float(re.sub(r'QQQ\s*', '', line).strip())
            strikes.append(val)
            continue
        v = parse_num(line)
        if v is not None:
            nbuf.append(v)
            if len(nbuf) == 9:
                row = dict(zip(
                    ['last','net','bid','ask','vol','iv','delta','gamma','oi'],
                    nbuf
                ))
                row['oi']    = int(abs(row['oi']))
                row['gamma'] = abs(row['gamma'])
                nbuf = []
                if section == 'calls':
                    call_rows.append(row)
                elif section == 'puts':
                    put_rows.append(row)
        else:
            if nbuf:
                nbuf = []

    flush()
    return blocks

# ── Calculo de GEX ────────────────────────────────────────────────────────
def calcular_gex(blocks, precio):
    S2 = precio ** 2 * 0.01 / 1e6   # resultado directo en M$

    gex_por_strike = {}
    gex_por_venc   = {}
    detalle        = []

    for blk in blocks:
        exp   = blk['expiry']
        strk  = blk['strikes']
        calls = blk['calls']
        puts  = blk['puts']
        n     = min(len(strk), len(calls), len(puts))

        g_venc = 0.0
        for i in range(n):
            k  = strk[i]
            gc = calls[i]['gamma'] * calls[i]['oi'] * 100 * S2
            gp = puts[i]['gamma']  * puts[i]['oi']  * 100 * S2
            gnet = gc - gp
            g_venc += gnet
            gex_por_strike[k] = gex_por_strike.get(k, 0.0) + gnet

            if calls[i]['gamma'] > 0 or puts[i]['gamma'] > 0:
                detalle.append({
                    'expiry': exp, 'strike': k,
                    'gex_M': round(gnet, 3),
                    'call_gamma': calls[i]['gamma'], 'call_oi': calls[i]['oi'],
                    'put_gamma':  puts[i]['gamma'],  'put_oi':  puts[i]['oi'],
                })

        gex_por_venc[exp] = round(g_venc, 3)

    total_M = sum(gex_por_venc.values())

    flip = None
    acum = 0.0
    for k in sorted(gex_por_strike):
        prev = acum
        acum += gex_por_strike[k]
        if prev >= 0 and acum < 0 and flip is None:
            flip = k
    if flip is None and gex_por_strike:
        flip = min(gex_por_strike, key=lambda k: gex_por_strike[k])

    estado = 'positivo_alto' if total_M > 1000 else \
             'positivo'      if total_M > 0    else \
             'neutro'        if total_M > -500  else \
             'negativo'      if total_M > -2000 else \
             'negativo_extremo'

    return {
        'valor_total':         round(total_M * 1e6, 0),
        'valor_total_M':       round(total_M, 2),
        'valor_total_B':       round(total_M / 1000, 4),
        'gamma_flip_level':    flip,
        'dist_gamma_flip_pct': round((flip - precio)/precio*100, 2) if flip else None,
        'estado':              estado,
        'fuente':              'gex_parser_local',
        'precio_referencia':   precio,
        'n_vencimientos':      len(gex_por_venc),
        'n_strikes_con_gamma': len([d for d in detalle if d['call_gamma']>0 or d['put_gamma']>0]),
        'gex_por_vencimiento': gex_por_venc,
        'top10_strikes_M':     sorted(detalle, key=lambda d: abs(d['gex_M']), reverse=True)[:10],
    }

# ── Calculo de Max Pain + Top OI por vencimiento ──────────────────────────
def calcular_maxpain_y_oi(blocks, precio):
    """
    Por cada vencimiento devuelve:
      - max_pain: strike donde calls_ITM + puts_ITM es MINIMO
      - top_calls: top 5 calls por OI (resistencias)
      - top_puts:  top 5 puts  por OI (soportes)
      - resistencia_principal: call con mas OI cerca del precio (0% a +5%)
      - soporte_principal:     put  con mas OI cerca del precio (-5% a 0%)
      - rango_semana: techo (top call) y suelo (top put) en zona +/-3%
    """
    salida = {}

    for blk in blocks:
        exp   = blk['expiry']
        strk  = blk['strikes']
        calls = blk['calls']
        puts  = blk['puts']
        n     = min(len(strk), len(calls), len(puts))

        oi_calls = {strk[i]: calls[i]['oi'] for i in range(n)}
        oi_puts  = {strk[i]: puts[i]['oi']  for i in range(n)}

        # Max Pain
        dolor = {}
        candidatos = sorted(set(strk[:n]))
        for S_cand in candidatos:
            d_c = sum(max(0, S_cand - k) * oi for k, oi in oi_calls.items())
            d_p = sum(max(0, k - S_cand) * oi for k, oi in oi_puts.items())
            dolor[S_cand] = (d_c + d_p) * 100

        max_pain = min(dolor, key=dolor.get) if dolor else None

        # Top OI
        top_calls = sorted(
            [{'strike': k, 'oi': v, 'dist': round((k - precio) / precio * 100, 2)}
             for k, v in oi_calls.items() if v > 0],
            key=lambda x: x['oi'], reverse=True
        )[:5]
        top_puts = sorted(
            [{'strike': k, 'oi': v, 'dist': round((k - precio) / precio * 100, 2)}
             for k, v in oi_puts.items() if v > 0],
            key=lambda x: x['oi'], reverse=True
        )[:5]

        # Resistencia: call con mas OI en zona [precio, precio+5%]
        cand_r = [c for c in top_calls if c['strike'] >= precio and c['dist'] <= 5]
        resistencia = max(cand_r, key=lambda x: x['oi']) if cand_r else (top_calls[0] if top_calls else None)

        # Soporte: put con mas OI en zona [precio-5%, precio]
        cand_s = [p for p in top_puts if p['strike'] <= precio and p['dist'] >= -5]
        soporte = max(cand_s, key=lambda x: x['oi']) if cand_s else (top_puts[0] if top_puts else None)

        # Rango semanal: techo y suelo en zona +/-3%
        techo_cand = [c for c in top_calls if abs(c['dist']) <= 3 and c['strike'] >= precio]
        suelo_cand = [p for p in top_puts  if abs(p['dist']) <= 3 and p['strike'] <= precio]
        techo = techo_cand[0]['strike'] if techo_cand else (resistencia['strike'] if resistencia else None)
        suelo = suelo_cand[0]['strike'] if suelo_cand else (soporte['strike'] if soporte else None)
        amplitud_pct = round((techo - suelo) / precio * 100, 2) if (techo and suelo) else None

        salida[exp] = {
            'max_pain':             max_pain,
            'dist_max_pain_pct':    round((max_pain - precio) / precio * 100, 2) if max_pain else None,
            'top_calls':            top_calls,
            'top_puts':             top_puts,
            'resistencia_principal': resistencia,
            'soporte_principal':     soporte,
            'rango_semana': {
                'techo': techo,
                'suelo': suelo,
                'amplitudPct': amplitud_pct,
            } if (techo and suelo) else None,
        }

    return salida

# ── Guardado ──────────────────────────────────────────────────────────────
def guardar_resultados(res, origen_path):
    salida_dir = Path(origen_path).parent
    archivos = [salida_dir / 'gex_manual.json']
    for ruta in [
        r'C:\Users\m21lo\nq-proxy',
        r'C:\Users\m21lo\PROYECTO_NASDAQ_UNIFICADO',
    ]:
        p = Path(ruta)
        if p.exists():
            archivos.append(p / 'gex_manual.json')

    guardados = []
    for dest in archivos:
        try:
            dest.write_text(json.dumps(res, indent=2, ensure_ascii=False))
            guardados.append(str(dest))
        except Exception as e:
            print(f"  [!] No se pudo guardar en {dest}: {e}")
    return guardados

# ── Main ───────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nEjemplo:")
        print("  python gex_parser.py opciones.txt 705.06")
        sys.exit(1)

    filepath = sys.argv[1]
    precio   = float(sys.argv[2]) if len(sys.argv) > 2 else PRECIO_DEFAULT

    print(f"\n{'='*65}")
    print(f"  GEX PARSER v1.1  -  QQQ Options Chain")
    print(f"{'='*65}")
    print(f"  Archivo : {filepath}")
    print(f"  Precio  : {precio}")
    print(f"{'='*65}\n")

    if not Path(filepath).exists():
        print(f"[ERROR] Archivo no encontrado: {filepath}")
        sys.exit(1)

    blocks = parse_file(filepath)
    if not blocks:
        print("[ERROR] No se detectaron bloques de opciones.")
        sys.exit(1)

    print(f"Vencimientos detectados: {len(blocks)}")
    for b in blocks:
        n_gamma_c = sum(1 for c in b['calls'] if c['gamma'] > 0)
        n_gamma_p = sum(1 for p in b['puts']  if p['gamma'] > 0)
        print(f"  {b['expiry']:<25}  {len(b['strikes']):>3} strikes  "
              f"  calls con gamma: {n_gamma_c:>3}  puts con gamma: {n_gamma_p:>3}")

    # GEX
    res = calcular_gex(blocks, precio)
    # Max Pain + Top OI
    mp_data = calcular_maxpain_y_oi(blocks, precio)
    res['maxpain_por_vencimiento'] = mp_data

    if mp_data:
        primer_exp = list(mp_data.keys())[0]
        primer = mp_data[primer_exp]
        res['vencimiento_proximo'] = {
            'expiry':                primer_exp,
            'max_pain':              primer['max_pain'],
            'dist_max_pain_pct':     primer['dist_max_pain_pct'],
            'resistencia_principal': primer['resistencia_principal'],
            'soporte_principal':     primer['soporte_principal'],
            'top_calls':             primer['top_calls'],
            'top_puts':              primer['top_puts'],
            'rango_semana':          primer['rango_semana'],
        }

    res['generado'] = datetime.now().isoformat()

    # ── Mostrar GEX ─────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    g = res['valor_total_M']
    estado_str = {
        'positivo_alto':    'POSITIVO ALTO  - dealers anclan precio, baja vol',
        'positivo':         'POSITIVO       - dealers compran caidas',
        'neutro':           'NEUTRO         - zona de transicion',
        'negativo':         'NEGATIVO       - dealers amplifican movimientos',
        'negativo_extremo': 'NEGATIVO EXTR. - volatilidad amplificada, cuidado',
    }[res['estado']]

    print(f"  GEX TOTAL    : {g:>+10.1f} M$  ({res['valor_total_B']:+.3f}B)")
    print(f"  Estado       : {estado_str}")
    if res['gamma_flip_level']:
        print(f"  Gamma Flip   : {res['gamma_flip_level']:.0f}  ({res['dist_gamma_flip_pct']:+.2f}% vs precio {precio})")
    print(f"  Vencimientos : {res['n_vencimientos']}")
    print(f"  Strikes GEX  : {res['n_strikes_con_gamma']}")
    print(f"{'='*65}")

    # ── Mostrar Max Pain por vencimiento ────────────────────────────────
    print(f"\nMAX PAIN por vencimiento:")
    for exp, mp in list(mp_data.items())[:5]:
        if mp['max_pain']:
            print(f"  {exp:<25}  MP = {mp['max_pain']:.0f}  ({mp['dist_max_pain_pct']:+.2f}%)")

    # ── Mostrar Vencimiento Proximo (lo que se autorrellena) ────────────
    if res.get('vencimiento_proximo'):
        vp = res['vencimiento_proximo']
        print(f"\nVENCIMIENTO PROXIMO ({vp['expiry']}) - se auto-rellena en el dashboard:")
        if vp.get('max_pain'):
            print(f"  Max Pain       : {vp['max_pain']:.0f}  ({vp['dist_max_pain_pct']:+.2f}%)")
        if vp.get('resistencia_principal'):
            r = vp['resistencia_principal']
            print(f"  Resistencia    : {r['strike']:.0f}  (OI={r['oi']:,})")
        if vp.get('soporte_principal'):
            s = vp['soporte_principal']
            print(f"  Soporte        : {s['strike']:.0f}  (OI={s['oi']:,})")
        if vp.get('rango_semana'):
            r = vp['rango_semana']
            print(f"  Rango semanal  : {r['suelo']:.0f} - {r['techo']:.0f}  (amplitud {r['amplitudPct']:.1f}%)")

    # ── Guardar ─────────────────────────────────────────────────────────
    guardados = guardar_resultados(res, filepath)
    print(f"\nArchivos guardados:")
    for g_path in guardados:
        print(f"  OK  {g_path}")

    print(f"\n[OK] El proximo run de actualizar_radar.py leera estos datos.")
    print(f"     Se rellenaran automaticamente:")
    print(f"       * Panel Derivados Avanzados (GEX, Gamma Flip)")
    print(f"       * Inputs Radar 2-5D (oi-precio, oi-maxpain, oi-resist, oi-soporte, sdx-gex)")
    print(f"       * Modulo Paredes de Opciones (Max Pain + Top OI)")
    print()

if __name__ == '__main__':
    main()
