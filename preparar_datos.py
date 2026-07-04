"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   PREPARAR_DATOS.py  —  Traductor de descargas manuales                       ║
║   Ruta prevista:  C:\\Users\\m21lo\\nq-proxy\\preparar_datos.py                  ║
║                                                                              ║
║   QUÉ HACE                                                                    ║
║   Lee la carpeta   DESCARGAS DIARIAS  (donde tú vuelcas los archivos, con    ║
║   nombres que cambian de fecha) y genera copias CANÓNICAS dentro de          ║
║   DATOS_CSV/  con el nombre y formato EXACTOS que esperan actualizar_radar.py ║
║   y motor_manengis.py. Así el motor no necesita cambios.                     ║
║                                                                              ║
║   - Identifica cada archivo por su PREFIJO (ignora la fecha del nombre).      ║
║   - Abre el archivo y comprueba la FECHA REAL de dentro (no la del nombre).   ║
║   - Si hay varias versiones del mismo tipo, usa la de fecha interna más       ║
║     reciente y MUEVE (nunca borra) las antiguas a  DESCARGAS DIARIAS/_procesados. ║
║   - Deja un informe claro por consola y en  preparar_datos.log.              ║
║                                                                              ║
║   ORDEN DE EJECUCIÓN DIARIO                                                   ║
║       python preparar_datos.py            (genera DATOS_CSV)                  ║
║       python actualizar_radar.py          (el maestro, ya normal)            ║
║                                                                              ║
║   OPCIONES                                                                    ║
║       --dry-run   Solo informa; no escribe ni mueve nada (para probar).      ║
║       --no-move   Genera DATOS_CSV pero no archiva duplicados antiguos.       ║
║       --src RUTA  Cambiar carpeta de descargas (por defecto DESCARGAS DIARIAS)║
║       --dst RUTA  Cambiar carpeta de salida    (por defecto DATOS_CSV)        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
import csv
import sys
import glob
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime, date

# ─────────────────────────────────────────────────────────────────────────────
#  RUTAS (por defecto, relativas a donde está este script)
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

def build_paths(args):
    src = Path(args.src).resolve() if args.src else (BASE_DIR / "DESCARGAS DIARIAS")
    dst = Path(args.dst).resolve() if args.dst else (BASE_DIR / "DATOS_CSV")
    return src, dst

# Umbral (en días de calendario) para avisar de que un dato está anticuado
DIAS_AVISO_OBSOLETO = 12

# El COT del NASDAQ-100 mini en el informe CFTC "Financial Futures" (TFF)
COT_CODE = "209742"

# Columnas que el motor lee del COT (leer_cot_csv en actualizar_radar.py)
COT_DATE_CANDIDATES = [
    "Report_Date_as_YYYY-MM-DD",
    "Report_Date_as_MM_DD_YYYY",
    "Report_Date_as_YYYY_MM_DD",
]
COT_OUT_COLS = [
    "CFTC_Contract_Market_Code",
    "Report_Date_as_YYYY-MM-DD",
    "Open_Interest_All",
    "Dealer_Positions_Long_All",
    "Dealer_Positions_Short_All",
    "Asset_Mgr_Positions_Long_All",
    "Asset_Mgr_Positions_Short_All",
    "Lev_Money_Positions_Long_All",
    "Lev_Money_Positions_Short_All",
]

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

log = logging.getLogger("preparar_datos")


# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────
def configurar_log(dst_parent: Path):
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fmt = logging.Formatter("%(message)s")
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)
    try:
        fh = logging.FileHandler(dst_parent / "preparar_datos.log", mode="w", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
        log.addHandler(fh)
    except Exception:
        pass


def parse_fecha(s):
    """Convierte muchos formatos de fecha a datetime.date. None si no puede."""
    if s is None:
        return None
    s = str(s).strip().strip('"')
    if not s or s == ".":
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%Y %I:%M:%S %p",
                "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def fecha_en_nombre(nombre):
    """Extrae una fecha del nombre de archivo (YYYY-MM-DD o YYYYMMDD). None si no hay."""
    m = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", nombre)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def safe_float(s):
    try:
        return float(str(s).strip().replace(",", ""))
    except (ValueError, TypeError):
        return None


def buscar(src: Path, patron):
    """Devuelve lista de Paths que casan con el patrón glob (case-insensitive-ish)."""
    res = []
    for p in src.glob(patron):
        if p.is_file():
            res.append(p)
    # también en mayúsculas por si acaso
    for p in src.glob(patron.upper()):
        if p.is_file() and p not in res:
            res.append(p)
    return sorted(res)


def max_fecha_interna(path, leer_fechas_fn):
    """Aplica leer_fechas_fn(path)->set/list de dates y devuelve la máxima."""
    try:
        fechas = [f for f in leer_fechas_fn(path) if f]
        return max(fechas) if fechas else None
    except Exception:
        return None


def dias_desde(f):
    if not f:
        return None
    return (date.today() - f).days


def escribir_csv(dst_path, cabecera, filas, dry):
    if dry:
        return
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_path.with_suffix(dst_path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cabecera)
        w.writerows(filas)
    os.replace(tmp, dst_path)


# ─────────────────────────────────────────────────────────────────────────────
#  LECTORES DE FECHA (para verificar "fecha real dentro del archivo")
# ─────────────────────────────────────────────────────────────────────────────
def fechas_col(path, col_names, encoding="utf-8", skip_preamble=False):
    """Lee un CSV y devuelve las fechas de la primera columna que exista de col_names."""
    fechas = []
    with open(path, newline="", encoding=encoding, errors="replace") as f:
        lineas = f.readlines()
    # localizar la cabecera real (para archivos con preámbulo legal, ej. CBOE)
    idx_cab = 0
    if skip_preamble:
        for i, ln in enumerate(lineas[:15]):
            low = ln.lower()
            if low.startswith("date,") or low.startswith('"date"') or low.startswith("date\t"):
                idx_cab = i
                break
    reader = csv.DictReader(lineas[idx_cab:])
    for row in reader:
        for c in col_names:
            if c in row:
                d = parse_fecha(row.get(c))
                if d:
                    fechas.append(d)
                break
    return fechas


# ─────────────────────────────────────────────────────────────────────────────
#  HANDLERS POR DATASET
# ─────────────────────────────────────────────────────────────────────────────
class Resultado:
    def __init__(self, nombre):
        self.nombre = nombre
        self.origen = None
        self.fecha_interna = None
        self.filas = None
        self.salidas = []
        self.estado = "—"
        self.aviso = None

    def linea_informe(self):
        f = self.fecha_interna.isoformat() if self.fecha_interna else "?"
        org = self.origen.name if self.origen else "(no encontrado)"
        fil = str(self.filas) if self.filas is not None else "-"
        return (self.nombre, self.estado, org, f, fil, self.aviso or "")


def copiar_tal_cual(src_file, dst_file, dry):
    if dry:
        return
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_file, dst_file)


def elegir_mas_reciente(candidatos, leer_fechas_fn):
    """De una lista de archivos del mismo tipo, devuelve (elegido, {path:fecha})."""
    fechas = {}
    for c in candidatos:
        f = max_fecha_interna(c, leer_fechas_fn) or fecha_en_nombre(c.name)
        fechas[c] = f
    # el más reciente por fecha interna; empate -> mtime
    def clave(p):
        return (fechas[p] or date.min, p.stat().st_mtime)
    elegido = max(candidatos, key=clave) if candidatos else None
    return elegido, fechas


def h_copia_fija(src, dst, dry, nombre, patron, dst_name, date_cols):
    """VIX_History.csv / VVIX_History.csv: copia directa, verifica fecha interna."""
    r = Resultado(nombre)
    cands = buscar(src, patron)
    if not cands:
        r.estado = "FALTA"
        return r
    leer = lambda p: fechas_col(p, date_cols)
    elegido, fechas = elegir_mas_reciente(cands, leer)
    r.origen = elegido
    r.fecha_interna = fechas.get(elegido)
    copiar_tal_cual(elegido, dst / dst_name, dry)
    r.salidas = [dst_name]
    r.estado = "OK"
    r.filas = sum(1 for _ in open(elegido, encoding="utf-8", errors="replace")) - 1
    _avisar_obsoleto(r)
    return r


def h_dix(src, dst, dry):
    r = Resultado("DIX / GEX")
    cands = buscar(src, "squeezemetrics_dix_*.csv") + buscar(src, "DIX.csv")
    cands = list(dict.fromkeys(cands))
    if not cands:
        r.estado = "FALTA"
        return r
    leer = lambda p: fechas_col(p, ["date", "DATE"])
    elegido, fechas = elegir_mas_reciente(cands, leer)
    r.origen = elegido
    r.fecha_interna = fechas.get(elegido)
    # validar columnas
    with open(elegido, newline="", encoding="utf-8", errors="replace") as f:
        cab = f.readline().strip().lower()
    if "dix" not in cab or "gex" not in cab:
        r.estado = "ERROR"
        r.aviso = "no tiene columnas date/price/dix/gex"
        return r
    copiar_tal_cual(elegido, dst / "DIX.csv", dry)
    r.salidas = ["DIX.csv"]
    r.estado = "OK"
    r.filas = sum(1 for _ in open(elegido, encoding="utf-8", errors="replace")) - 1
    _avisar_obsoleto(r)
    return r


def h_skew(src, dst, dry):
    """cboe_skew_*.csv (Date,Open,High,Low,Close + preámbulo) -> DATE,SKEW (ISO)."""
    r = Resultado("SKEW")
    cands = buscar(src, "cboe_skew_*.csv") + buscar(src, "skew-history.csv") + buscar(src, "SKEW_History.csv")
    cands = list(dict.fromkeys(cands))
    if not cands:
        r.estado = "FALTA"
        return r
    leer = lambda p: fechas_col(p, ["Date", "DATE"], skip_preamble=True)
    elegido, fechas = elegir_mas_reciente(cands, leer)
    r.origen = elegido
    # leer filas
    with open(elegido, newline="", encoding="utf-8", errors="replace") as f:
        lineas = f.readlines()
    idx_cab = 0
    for i, ln in enumerate(lineas[:15]):
        if ln.lower().startswith("date,"):
            idx_cab = i
            break
    reader = csv.DictReader(lineas[idx_cab:])
    filas = []
    for row in reader:
        d = parse_fecha(row.get("Date") or row.get("DATE"))
        val = None
        for c in ("SKEW", "Close", "CLOSE"):
            if c in row and safe_float(row[c]) is not None:
                val = safe_float(row[c]); break
        if d and val is not None:
            filas.append((d.isoformat(), val))
    if not filas:
        r.estado = "ERROR"
        r.aviso = "no se pudieron extraer valores SKEW"
        return r
    filas.sort()
    r.fecha_interna = parse_fecha(filas[-1][0])
    r.filas = len(filas)
    # el motor Radar quiere skew-history.csv ; Manengis quiere SKEW_History.csv
    escribir_csv(dst / "skew-history.csv", ["DATE", "SKEW"], filas, dry)
    escribir_csv(dst / "SKEW_History.csv", ["DATE", "SKEW"], filas, dry)
    r.salidas = ["skew-history.csv", "SKEW_History.csv"]
    r.estado = "OK"
    _avisar_obsoleto(r)
    return r


def h_qqq(src, dst, dry):
    """qqq_options_chain_*.csv (Barchart) -> qqq_quotedata.csv (copia tal cual)."""
    r = Resultado("QQQ opciones")
    cands = buscar(src, "qqq_options_chain_*.csv") + buscar(src, "qqq_quotedata.csv")
    cands = list(dict.fromkeys(cands))
    if not cands:
        r.estado = "FALTA"
        return r

    def fecha_qqq(p):
        # la fecha va en la cabecera: "Date: 1 de julio de 2026 a las ..."
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                cab = "".join([next(f) for _ in range(3)])
        except Exception:
            return []
        m = re.search(r"Date:\s*(\d{1,2})\s+de\s+([a-zA-Zñ]+)\s+de\s+(\d{4})", cab, re.I)
        if m:
            mes = MESES_ES.get(m.group(2).lower())
            if mes:
                try:
                    return [date(int(m.group(3)), mes, int(m.group(1)))]
                except ValueError:
                    pass
        fn = fecha_en_nombre(p.name)
        return [fn] if fn else []

    elegido, fechas = elegir_mas_reciente(cands, fecha_qqq)
    r.origen = elegido
    r.fecha_interna = fechas.get(elegido)
    copiar_tal_cual(elegido, dst / "qqq_quotedata.csv", dry)
    r.salidas = ["qqq_quotedata.csv"]
    r.estado = "OK"
    r.filas = sum(1 for _ in open(elegido, encoding="utf-8", errors="replace"))
    _avisar_obsoleto(r)
    return r


def h_fred(src, dst, dry, nombre, patron, dst_name, val_col):
    """fred_*.csv (date,value) -> observation_date,<VAL_COL>  (formato que espera el motor)."""
    r = Resultado(nombre)
    cands = buscar(src, patron)
    if not cands:
        r.estado = "FALTA"
        return r
    leer = lambda p: fechas_col(p, ["date", "DATE", "observation_date"])
    elegido, fechas = elegir_mas_reciente(cands, leer)
    r.origen = elegido
    filas = []
    with open(elegido, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = parse_fecha(row.get("date") or row.get("DATE") or row.get("observation_date"))
            v = safe_float(row.get("value") or row.get(val_col))
            if d and v is not None:
                filas.append((d.isoformat(), v))
    if not filas:
        r.estado = "ERROR"; r.aviso = "sin filas numéricas"; return r
    filas.sort()
    r.fecha_interna = parse_fecha(filas[-1][0])
    r.filas = len(filas)
    escribir_csv(dst / dst_name, ["observation_date", val_col], filas, dry)
    r.salidas = [dst_name]
    r.estado = "OK"
    _avisar_obsoleto(r)
    return r


def h_cot(src, dst, dry):
    """
    Consolida TODO el histórico COT del NASDAQ mini (209742):
      F_TFF_2006_2016.csv  +  FinFut17..25.csv  +  cftc_cot_financial_futures_only_*.txt
    en un único  DATOS_CSV/COT/cot_209742_consolidado.txt  con la cabecera exacta
    que lee actualizar_radar.py.
    """
    r = Resultado("COT NASDAQ (209742)")
    fuentes = []
    fuentes += buscar(src, "F_TFF_*.csv")
    fuentes += buscar(src, "FinFut*.csv")
    fuentes += buscar(src, "cftc_cot_financial_futures_only_*.txt")
    fuentes += buscar(src, "cftc_cot_financial_futures_only_*.TXT")
    fuentes = list(dict.fromkeys(fuentes))
    if not fuentes:
        r.estado = "FALTA"
        return r

    por_fecha = {}   # date -> fila dict (deduplica; gana la última leída)
    n_fuentes_ok = 0
    for path in fuentes:
        try:
            with open(path, newline="", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                # localizar columna de fecha disponible en ESTE archivo
                date_col = next((c for c in COT_DATE_CANDIDATES if c in cols), None)
                if not date_col:
                    continue
                encontrados = 0
                for row in reader:
                    code = (row.get("CFTC_Contract_Market_Code") or "").strip().strip('"')
                    if code != COT_CODE:
                        continue
                    d = parse_fecha(row.get(date_col))
                    if not d:
                        continue
                    fila = {
                        "CFTC_Contract_Market_Code": COT_CODE,
                        "Report_Date_as_YYYY-MM-DD": d.isoformat(),
                        "Open_Interest_All": (row.get("Open_Interest_All") or "").strip(),
                        "Dealer_Positions_Long_All": (row.get("Dealer_Positions_Long_All") or "").strip(),
                        "Dealer_Positions_Short_All": (row.get("Dealer_Positions_Short_All") or "").strip(),
                        "Asset_Mgr_Positions_Long_All": (row.get("Asset_Mgr_Positions_Long_All") or "").strip(),
                        "Asset_Mgr_Positions_Short_All": (row.get("Asset_Mgr_Positions_Short_All") or "").strip(),
                        "Lev_Money_Positions_Long_All": (row.get("Lev_Money_Positions_Long_All") or "").strip(),
                        "Lev_Money_Positions_Short_All": (row.get("Lev_Money_Positions_Short_All") or "").strip(),
                    }
                    por_fecha[d] = fila
                    encontrados += 1
                if encontrados:
                    n_fuentes_ok += 1
        except Exception as e:
            log.info(f"    · aviso leyendo {path.name}: {e}")

    if not por_fecha:
        r.estado = "ERROR"
        r.aviso = f"ningún archivo contenía el código {COT_CODE}"
        return r

    fechas_ord = sorted(por_fecha.keys())
    r.fecha_interna = fechas_ord[-1]
    r.filas = len(fechas_ord)

    if not dry:
        cot_dir = dst / "COT"
        cot_dir.mkdir(parents=True, exist_ok=True)
        # limpiar .txt antiguos para que no queden semanas duplicadas/obsoletas
        for viejo in cot_dir.glob("*.txt"):
            try:
                viejo.unlink()
            except Exception:
                pass
        out = cot_dir / "cot_209742_consolidado.txt"
        tmp = out.with_suffix(".txt.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COT_OUT_COLS)
            w.writeheader()
            for d in fechas_ord:
                w.writerow(por_fecha[d])
        os.replace(tmp, out)

    r.salidas = ["COT/cot_209742_consolidado.txt"]
    r.origen = fuentes[0]  # representativo
    r.estado = "OK"
    r.aviso = f"{r.filas} semanas de {n_fuentes_ok} archivos"
    if r.filas < 500:
        r.aviso += "  (¡pocas semanas! percentiles poco fiables)"
    _avisar_obsoleto(r)
    return r


MESES_EN = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}

def h_pcr(src, dst_root, dry):
    """
    cboe_market_stats_*.csv (comas, con preámbulo 'Fecha,<fecha>' y 'Ratios,Value')
    -> PCR.txt en la RAÍZ de nq-proxy (junto a actualizar_radar.py, NO en DATOS_CSV),
    con el formato de tabulaciones que espera parsear_pcr_txt():
        05 June 2026
        TOTAL PUT/CALL RATIO<TAB>0.88
        EQUITY PUT/CALL RATIO<TAB>0.64
        INDEX PUT/CALL RATIO<TAB>1.01
        SPX + SPXW PUT/CALL RATIO<TAB>1.09
    """
    r = Resultado("PCR (Put/Call Ratio)")
    cands = buscar(src, "cboe_market_stats_*.csv")
    if not cands:
        r.estado = "FALTA"
        return r

    def fecha_pcr(p):
        try:
            with open(p, newline="", encoding="utf-8", errors="replace") as f:
                cab = f.readline()
        except Exception:
            return []
        # cabecera tipo: Fecha,30 June 2026
        m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", cab)
        if m:
            meses_es = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
                        "julio":7,"agosto":8,"septiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
            meses_en = {v.lower(): k for k, v in MESES_EN.items()}
            mes_txt = m.group(2).lower()
            mes = meses_en.get(mes_txt) or meses_es.get(mes_txt)
            if mes:
                try:
                    return [date(int(m.group(3)), mes, int(m.group(1)))]
                except ValueError:
                    pass
        fn = fecha_en_nombre(p.name)
        return [fn] if fn else []

    elegido, fechas = elegir_mas_reciente(cands, fecha_pcr)
    r.origen = elegido
    r.fecha_interna = fechas.get(elegido)

    # Leer las filas "ETIQUETA,valor" del CSV
    etiquetas = {
        "TOTAL PUT/CALL RATIO": None,
        "EQUITY PUT/CALL RATIO": None,
        "INDEX PUT/CALL RATIO": None,
        "SPX + SPXW PUT/CALL RATIO": None,
    }
    with open(elegido, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            if not row:
                continue
            clave = row[0].strip().strip('"')
            if clave in etiquetas and len(row) > 1:
                v = safe_float(row[1])
                if v is not None:
                    etiquetas[clave] = v

    if all(v is None for v in etiquetas.values()):
        r.estado = "ERROR"
        r.aviso = "no se encontraron ratios en el CSV"
        return r

    if not r.fecha_interna:
        r.fecha_interna = date.today()
    linea_fecha = f"{r.fecha_interna.day:02d} {MESES_EN[r.fecha_interna.month]} {r.fecha_interna.year}"

    lineas = [linea_fecha]
    for etiqueta, valor in etiquetas.items():
        if valor is not None:
            lineas.append(f"{etiqueta}\t{valor}")

    if not dry:
        dst_root.mkdir(parents=True, exist_ok=True)
        out = dst_root / "PCR.txt"
        tmp = out.with_suffix(".txt.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lineas) + "\n")
        os.replace(tmp, out)

    r.filas = len([v for v in etiquetas.values() if v is not None])
    r.salidas = ["../PCR.txt  (raíz de nq-proxy, NO en DATOS_CSV)"]
    r.estado = "OK"
    _avisar_obsoleto(r)
    return r


# Orden y mapeo EXACTOS de las 22 columnas de cboe_ratios_historico.csv,
# tal y como aparecen etiquetadas dentro de cada cboe_market_stats_*.csv
PCR_HIST_COLUMNAS = [
    ("TOTAL_PUT_CALL_RATIO",   "TOTAL PUT/CALL RATIO"),
    ("INDEX_PUT_CALL_RATIO",   "INDEX PUT/CALL RATIO"),
    ("ETP_PUT_CALL_RATIO",     "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO"),
    ("EQUITY_PUT_CALL_RATIO",  "EQUITY PUT/CALL RATIO"),
    ("VIX_PUT_CALL_RATIO",     "CBOE VOLATILITY INDEX (VIX) PUT/CALL RATIO"),
    ("SPX_SPXW_PUT_CALL_RATIO","SPX + SPXW PUT/CALL RATIO"),
    ("OEX_PUT_CALL_RATIO",     "OEX PUT/CALL RATIO"),
    ("MRUT_PUT_CALL_RATIO",    "MRUT PUT/CALL RATIO"),
    ("MXEA_PUT_CALL_RATIO",    "MXEA PUT/CALL RATIO"),
    ("MXEF_PUT_CALL_RATIO",    "MXEF PUT/CALL RATIO"),
    ("MXACW_PUT_CALL_RATIO",   "MXACW PUT/CALL RATIO"),
    ("MXWLD_PUT_CALL_RATIO",   "MXWLD PUT/CALL RATIO"),
    ("MXUSA_PUT_CALL_RATIO",   "MXUSA PUT/CALL RATIO"),
    ("CBTX_PUT_CALL_RATIO",    "CBTX PUT/CALL RATIO"),
    ("MBTX_PUT_CALL_RATIO",    "MBTX PUT/CALL RATIO"),
    ("SPEQX_PUT_CALL_RATIO",   "SPEQX PUT/CALL RATIO"),
    ("SPEQW_PUT_CALL_RATIO",   "SPEQW PUT/CALL RATIO"),
    ("MGTN_PUT_CALL_RATIO",    "MGTN PUT/CALL RATIO"),
    ("MGTNW_PUT_CALL_RATIO",   "MGTNW PUT/CALL RATIO"),
    ("DJX_PUT_CALL_RATIO",     "DJX PUT/CALL RATIO"),
    ("DJXW_PUT_CALL_RATIO",    "DJXW PUT/CALL RATIO"),
    ("XSPBX_PUT_CALL_RATIO",   "XSPBX PUT/CALL RATIO"),
    ("XSPBW_PUT_CALL_RATIO",   "XSPBW PUT/CALL RATIO"),
]
PCR_HIST_CABECERA = ["Fecha"] + [c[0] for c in PCR_HIST_COLUMNAS]


def _leer_market_stats_fecha_y_ratios(path):
    """Lee un cboe_market_stats_*.csv suelto: devuelve (date, {col_canonica: valor})."""
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            lineas = f.readlines()
    except Exception:
        return None, {}
    fecha = None
    for ln in lineas[:3]:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", ln)
        if m:
            meses_en_rev = {v.lower(): k for k, v in MESES_EN.items()}
            mes = meses_en_rev.get(m.group(2).lower())
            if mes:
                try:
                    fecha = date(int(m.group(3)), mes, int(m.group(1)))
                except ValueError:
                    fecha = None
            break
    valores = {}
    for ln in lineas:
        clave, _, resto = ln.strip().partition(",")
        clave = clave.strip().strip('"').upper()
        for col_canonica, etiqueta in PCR_HIST_COLUMNAS:
            if clave == etiqueta.upper():
                v = safe_float(resto)
                if v is not None:
                    valores[col_canonica] = v
                break
    return fecha, valores


def h_pcr_ratios_historico(src, dst, dry):
    """
    Construye/actualiza DATOS_CSV/PCR_RATIOS_HISTORICO.csv AUTOMATICAMENTE
    a partir de TODOS los cboe_market_stats_*.csv sueltos que haya en
    DESCARGAS DIARIAS (uno por dia, cada uno con la fecha real dentro).

    IMPORTANTE (corregido tras aviso del usuario): cboe_ratios_historico.csv
    NO es un export acumulativo de CBOE — lo estaba construyendo el usuario
    A MANO copiando cada dia los valores, lo cual ya causo errores de
    transcripcion reales (ej. "11.0" en vez de "1.0"/"1.1" en varias filas).
    Este handler elimina ese trabajo manual: cada ejecucion lee todos los
    cboe_market_stats_*.csv presentes, extrae su fecha y sus 22 ratios, y
    los fusiona (upsert por fecha) sobre el historico ya acumulado en
    DATOS_CSV/PCR_RATIOS_HISTORICO.csv de la ejecucion anterior. Si es la
    primera vez y no existe aun, se siembra una sola vez desde
    cboe_ratios_historico.csv (el archivo manual del usuario) si esta
    presente, para no perder el historico 2019-2026 ya construido.
    """
    r = Resultado("PCR ratios historico (auto)")

    acumulado = {}  # date -> {col: valor}

    # 1) Semilla: historico ya acumulado en ejecuciones previas
    existente = dst / "PCR_RATIOS_HISTORICO.csv"
    fuente_semilla = None
    if existente.exists():
        fuente_semilla = existente
    else:
        manual = buscar(src, "cboe_ratios_historico.csv")
        if manual:
            fuente_semilla = manual[0]
    if fuente_semilla:
        with open(fuente_semilla, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = parse_fecha(row.get("Fecha"))
                if not d:
                    continue
                fila = {}
                for col_canonica, _ in PCR_HIST_COLUMNAS:
                    v = safe_float(row.get(col_canonica))
                    if v is not None:
                        fila[col_canonica] = v
                acumulado[d] = fila

    n_semilla = len(acumulado)

    # 2) Fusionar TODOS los cboe_market_stats_*.csv sueltos de hoy/dias recientes
    diarios = buscar(src, "cboe_market_stats_*.csv")
    n_nuevos = 0
    n_actualizados = 0
    procesados = []
    for path in diarios:
        fecha, valores = _leer_market_stats_fecha_y_ratios(path)
        if not fecha or not valores:
            continue
        # outlier obvio de captura (valor >3 o <0.1 en cualquier ratio principal
        # TOTAL/INDEX/EQUITY/SPX) -> se descarta esa fila entera, mejor "sin dato"
        # que un dato corrupto contaminando el percentil
        principales = ["TOTAL_PUT_CALL_RATIO", "INDEX_PUT_CALL_RATIO",
                        "EQUITY_PUT_CALL_RATIO", "SPX_SPXW_PUT_CALL_RATIO"]
        sospechoso = any(valores.get(c) is not None and (valores[c] > 3 or valores[c] < 0.05)
                          for c in principales)
        if sospechoso:
            log.warning(f"    [PCR-HIST] {path.name} → fecha {fecha}: valores fuera de rango, se descarta")
            continue
        if fecha in acumulado:
            n_actualizados += 1
        else:
            n_nuevos += 1
        acumulado[fecha] = valores
        procesados.append((fecha, path.name))

    if not acumulado:
        r.estado = "FALTA"
        return r

    fechas_ord = sorted(acumulado.keys())
    r.fecha_interna = fechas_ord[-1]
    r.filas = len(fechas_ord)
    r.origen = diarios[-1] if diarios else fuente_semilla

    if not dry:
        filas_out = []
        for d in fechas_ord:
            fila = acumulado[d]
            filas_out.append([d.isoformat()] + [fila.get(c, "") for c, _ in PCR_HIST_COLUMNAS])
        escribir_csv(dst / "PCR_RATIOS_HISTORICO.csv", PCR_HIST_CABECERA, filas_out, dry=False)

    r.salidas = ["PCR_RATIOS_HISTORICO.csv"]
    r.estado = "OK"
    detalle = f"semilla={n_semilla}d · +{n_nuevos} nuevos · {n_actualizados} actualizados de {len(diarios)} archivos sueltos"
    r.aviso = detalle
    _avisar_obsoleto(r)
    return r


def h_vix_futures_curve(src, dst, dry):
    """
    cboe_futures_settlement_*.csv (Product,Symbol,Expiration Date,Price)
    -> DATOS_CSV/VIX_FUTURES_CURVE.csv (solo filas Product==VX, ordenadas
    por fecha de vencimiento).

    Se usa cboe_futures_settlement (settlements limpios, sin '-') en vez de
    cboe_vix_futures_*.csv porque este ultimo suele venir con '-' en Last
    Price/High/Low fuera de horario de mercado; futures_settlement trae el
    settlement oficial de cada contrato siempre relleno.

    Da la curva de futuros VIX completa -> permite calcular contango/
    backwardation real (M2/M1) como señal adicional, distinta del ratio
    VIX spot / VIX3M que ya se usa.
    """
    r = Resultado("Curva futuros VIX (CBOE)")
    cands = buscar(src, "cboe_futures_settlement_*.csv")
    if not cands:
        r.estado = "FALTA"
        return r

    def fecha_settlement(p):
        return fechas_col(p, ["Expiration Date"])

    elegido, fechas = elegir_mas_reciente(cands, fecha_settlement)
    r.origen = elegido

    filas_vx = []
    with open(elegido, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("Product") or "").strip().upper() != "VX":
                continue
            d = parse_fecha(row.get("Expiration Date"))
            precio = safe_float(row.get("Price"))
            if d and precio is not None:
                filas_vx.append((d.isoformat(), row.get("Symbol", "").strip(), precio))
    if not filas_vx:
        r.estado = "ERROR"
        r.aviso = "no se encontraron contratos VX con precio"
        return r
    filas_vx.sort()
    r.filas = len(filas_vx)
    r.fecha_interna = fecha_en_nombre(elegido.name) or date.today()
    escribir_csv(dst / "VIX_FUTURES_CURVE.csv",
                 ["expiration_date", "symbol", "settlement"], filas_vx, dry)
    r.salidas = ["VIX_FUTURES_CURVE.csv"]
    r.estado = "OK"
    # aviso informativo con la pendiente M2/M1 (contango si >1)
    if len(filas_vx) >= 2:
        m1, m2 = filas_vx[0][2], filas_vx[1][2]
        if m1:
            ratio = round(m2 / m1, 4)
            r.aviso = f"M1={m1} M2={m2} ratio M2/M1={ratio} ({'contango' if ratio > 1 else 'backwardation'})"
    _avisar_obsoleto(r)
    return r


def h_vix_txt(src, dst_root, dry):
    """
    Genera VIX.txt en la raiz de nq-proxy (igual que PCR.txt), en el formato
    EXACTO que ya sabe leer parsear_vix_ts_txt() en actualizar_radar.py:
    lineas separadas por TAB con 7+ columnas
    (Symbol, Expiration MM/DD/YYYY, Last, Change, High, Low, Settlement, Volume).

    Ese parser YA EXISTE en el motor desde antes de esta sesion, pero
    esperaba que el usuario creara VIX.txt a mano (por eso el frontend
    mostraba "VX1/VX2: añade VIX.txt en nq-proxy"). Nadie lo habia conectado
    a una descarga automatica. Este handler cierra ese hueco:

    - Curva de contratos VX: de cboe_futures_settlement_*.csv (settlements
      siempre rellenos, ya usado en h_vix_futures_curve) — reformateamos
      la fecha a MM/DD/YYYY y ponemos el precio en la columna Settlement
      (Last se deja en "-", el parser cae automaticamente a Settlement).
    - VIX spot: de cboe_vix_futures_*.csv, fila "VIX,-,<last>,...", que SI
      suele traer el spot real aunque los futuros vengan con "-".
    """
    r = Resultado("VIX.txt (term structure real)")
    cands_settlement = buscar(src, "cboe_futures_settlement_*.csv")
    if not cands_settlement:
        r.estado = "FALTA"
        return r

    def fecha_settlement(p):
        return fechas_col(p, ["Expiration Date"])

    elegido, fechas = elegir_mas_reciente(cands_settlement, fecha_settlement)
    r.origen = elegido

    filas_vx = []
    with open(elegido, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("Product") or "").strip().upper() != "VX":
                continue
            d = parse_fecha(row.get("Expiration Date"))
            precio = safe_float(row.get("Price"))
            simbolo = (row.get("Symbol") or "").strip()
            if d and precio is not None and simbolo:
                filas_vx.append((d, simbolo, precio))
    if not filas_vx:
        r.estado = "ERROR"
        r.aviso = "no se encontraron contratos VX con precio en cboe_futures_settlement"
        return r
    filas_vx.sort()

    # VIX spot: buscar en cboe_vix_futures_*.csv la fila "VIX,-,<last>,..."
    vix_spot = None
    cands_vix = buscar(src, "cboe_vix_futures_*.csv")
    if cands_vix:
        elegido_vix, _ = elegir_mas_reciente(cands_vix, lambda p: [fecha_en_nombre(p.name)])
        with open(elegido_vix, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.reader(f):
                if row and row[0].strip().upper() == "VIX":
                    vix_spot = safe_float(row[2]) if len(row) > 2 else None
                    break

    lineas = []
    if vix_spot is not None:
        lineas.append(f"VIX\t-\t{vix_spot}\t-\t-\t-\t-\t-")
    for d, simbolo, precio in filas_vx:
        exp_mmddyyyy = f"{d.month:02d}/{d.day:02d}/{d.year:04d}"
        lineas.append(f"{simbolo}\t{exp_mmddyyyy}\t-\t-\t-\t-\t{precio}\t-")

    if not dry:
        dst_root.mkdir(parents=True, exist_ok=True)
        out = dst_root / "VIX.txt"
        tmp = out.with_suffix(".txt.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lineas) + "\n")
        os.replace(tmp, out)

    r.filas = len(lineas)
    r.fecha_interna = fecha_en_nombre(elegido.name) or date.today()
    r.salidas = ["../VIX.txt  (raíz de nq-proxy, NO en DATOS_CSV)"]
    r.estado = "OK"
    r.aviso = f"spot={'sí' if vix_spot is not None else 'NO (falta cboe_vix_futures)'} · {len(filas_vx)} contratos VX"
    _avisar_obsoleto(r)
    return r


def h_ici_flows(src, dst, dry):
    """
    ici_combined_flows_historical_*.xls (Investment Company Institute,
    "Long-Term Mutual Fund and ETF Flows") -> DATOS_CSV/ICI_FLOWS.csv

    El .xls trae UNA hoja con 2 bloques en las mismas columnas:
      - "Monthly fund flows" (histórico mensual, desde 2024)
      - "Estimated weekly fund flows" (últimas ~4-5 semanas, más reciente)
    Columnas (por posición, confirmado con archivo real):
      0=Fecha, 1=Total LT MF+ETF, 3=Equity Total, 5=Equity Domestic,
      7=Equity World, 9=Hybrid, 11=Bond Total, 13=Bond Taxable,
      15=Bond Municipal, 17=Commodity  (en millones de USD)

    Requiere pandas + xlrd (el .xls es formato binario antiguo, no XML).
    Si no están instalados, avisa con el pip install exacto en vez de
    petar sin explicación.
    """
    r = Resultado("ICI fund flows (mensual + semanal)")
    cands = buscar(src, "ici_combined_flows_historical_*.xls")
    if not cands:
        r.estado = "FALTA"
        return r
    elegido = cands[0]
    r.origen = elegido

    try:
        import pandas as pd
    except ImportError:
        r.estado = "ERROR"
        r.aviso = "falta 'pandas' — instala con: pip install pandas openpyxl xlrd"
        return r
    try:
        df = pd.read_excel(elegido, sheet_name=0, header=None)
    except ImportError:
        r.estado = "ERROR"
        r.aviso = "falta 'xlrd' para leer .xls — instala con: pip install xlrd"
        return r
    except Exception as e:
        r.estado = "ERROR"
        r.aviso = f"no se pudo leer el .xls: {e}"
        return r

    cols_idx = {
        "total_ltmf_etf": 1, "equity_total": 3, "equity_domestic": 5,
        "equity_world": 7, "hybrid": 9, "bond_total": 11,
        "bond_taxable": 13, "bond_municipal": 15, "commodity": 17,
    }
    filas_out = []
    tipo_actual = None
    for i in range(len(df)):
        primera = str(df.iloc[i, 0]).strip()
        if primera.lower().startswith("monthly fund flows"):
            tipo_actual = "mensual"
            continue
        if primera.lower().startswith("estimated weekly"):
            tipo_actual = "semanal"
            continue
        if tipo_actual is None:
            continue
        d = parse_fecha(primera)
        if not d:
            continue
        fila = {"fecha": d.isoformat(), "tipo": tipo_actual}
        valida = False
        for nombre, idx in cols_idx.items():
            v = safe_float(df.iloc[i, idx]) if idx < df.shape[1] else None
            fila[nombre] = v if v is not None else ""
            if v is not None:
                valida = True
        if valida:
            filas_out.append(fila)

    if not filas_out:
        r.estado = "ERROR"
        r.aviso = "no se encontraron filas válidas (¿cambió el formato del .xls?)"
        return r

    cabecera = ["fecha", "tipo"] + list(cols_idx.keys())
    filas_csv = [[f[c] for c in cabecera] for f in filas_out]
    escribir_csv(dst / "ICI_FLOWS.csv", cabecera, filas_csv, dry)

    fechas_validas = [parse_fecha(f["fecha"]) for f in filas_out]
    r.filas = len(filas_out)
    r.fecha_interna = max(fechas_validas)
    r.salidas = ["ICI_FLOWS.csv"]
    r.estado = "OK"
    n_sem = sum(1 for f in filas_out if f["tipo"] == "semanal")
    n_mes = sum(1 for f in filas_out if f["tipo"] == "mensual")
    r.aviso = f"{n_mes} filas mensuales + {n_sem} semanales"
    _avisar_obsoleto(r)
    return r
    d = dias_desde(r.fecha_interna)
    if d is not None and d > DIAS_AVISO_OBSOLETO:
        extra = f"dato de hace {d} días — ¿descarga nueva?"
        r.aviso = (r.aviso + " | " + extra) if r.aviso else extra
        if r.estado == "OK":
            r.estado = "OK*"


# ─────────────────────────────────────────────────────────────────────────────
#  ARCHIVADO DE DUPLICADOS ANTIGUOS (mover, nunca borrar)
# ─────────────────────────────────────────────────────────────────────────────
PREFIJOS_CON_FECHA = [
    "squeezemetrics_dix_",
    "cboe_skew_",
    "qqq_options_chain_",
    "cboe_market_stats_",
    "cboe_vix_futures_",
    "cboe_futures_settlement_",
    "ici_combined_flows_historical_",
]

def archivar_duplicados(src: Path, dry):
    """Para cada grupo con fecha en el nombre, deja el más reciente y mueve el resto."""
    procesados = src / "_procesados"
    movidos = []
    for pref in PREFIJOS_CON_FECHA:
        grupo = sorted([p for p in src.glob(pref + "*") if p.is_file()])
        if len(grupo) <= 1:
            continue
        # ordenar por fecha del nombre (fallback mtime); conservar el último
        def clave(p):
            return (fecha_en_nombre(p.name) or date.min, p.stat().st_mtime)
        grupo.sort(key=clave)
        antiguos = grupo[:-1]
        for viejo in antiguos:
            movidos.append(viejo.name)
            if not dry:
                procesados.mkdir(parents=True, exist_ok=True)
                destino = procesados / viejo.name
                if destino.exists():
                    destino = procesados / f"{viejo.stem}_{int(viejo.stat().st_mtime)}{viejo.suffix}"
                shutil.move(str(viejo), str(destino))
    return movidos


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Traductor DESCARGAS DIARIAS -> DATOS_CSV")
    ap.add_argument("--dry-run", action="store_true", help="Solo informa; no escribe ni mueve")
    ap.add_argument("--no-move", action="store_true", help="No archivar duplicados antiguos")
    ap.add_argument("--src", default=None, help="Carpeta de descargas")
    ap.add_argument("--dst", default=None, help="Carpeta de salida canónica")
    args = ap.parse_args()

    src, dst = build_paths(args)
    configurar_log(BASE_DIR)

    log.info("=" * 74)
    log.info("  PREPARAR_DATOS — traductor de descargas manuales")
    log.info("=" * 74)
    log.info(f"  Origen : {src}")
    log.info(f"  Salida : {dst}")
    if args.dry_run:
        log.info("  MODO   : DRY-RUN (no se escribe ni se mueve nada)")
    log.info("-" * 74)

    if not src.exists():
        log.error(f"  ERROR: no existe la carpeta de descargas:\n         {src}")
        log.error("  Crea la carpeta o pásala con --src")
        sys.exit(1)

    if not args.dry_run:
        dst.mkdir(parents=True, exist_ok=True)

    resultados = []
    # 6+ bloques canónicos
    resultados.append(h_copia_fija(src, dst, args.dry_run, "VIX",
                                   "VIX_History.csv", "VIX_History.csv", ["DATE"]))
    resultados.append(h_copia_fija(src, dst, args.dry_run, "VVIX",
                                   "VVIX_History.csv", "VVIX_History.csv", ["DATE"]))
    resultados.append(h_dix(src, dst, args.dry_run))
    resultados.append(h_skew(src, dst, args.dry_run))
    resultados.append(h_qqq(src, dst, args.dry_run))
    resultados.append(h_fred(src, dst, args.dry_run, "NFCI (cond. financieras)",
                             "fred_NFCI_*.csv", "NFCI.csv", "NFCI"))
    resultados.append(h_fred(src, dst, args.dry_run, "WALCL (balance Fed)",
                             "fred_WALCL_*.csv", "WALCL.csv", "WALCL"))
    resultados.append(h_cot(src, dst, args.dry_run))
    resultados.append(h_pcr(src, dst.parent, args.dry_run))
    resultados.append(h_pcr_ratios_historico(src, dst, args.dry_run))
    resultados.append(h_vix_futures_curve(src, dst, args.dry_run))
    resultados.append(h_vix_txt(src, dst.parent, args.dry_run))
    resultados.append(h_ici_flows(src, dst, args.dry_run))

    # informe
    log.info("")
    log.info("  RESULTADO:")
    log.info("  " + "-" * 72)
    log.info("  %-22s %-5s %-34s %-11s" % ("BLOQUE", "EST", "ORIGEN", "FECHA DATO"))
    log.info("  " + "-" * 72)
    n_ok = 0
    for r in resultados:
        nombre, estado, origen, fecha, filas, aviso = r.linea_informe()
        if estado.startswith("OK"):
            n_ok += 1
        log.info("  %-22s %-5s %-34s %-11s" % (nombre[:22], estado, origen[:34], fecha))
        for s in r.salidas:
            log.info("                         -> %s" % s)
        if aviso:
            log.info("                         (%s)" % aviso)
    log.info("  " + "-" * 72)
    log.info(f"  {n_ok}/{len(resultados)} bloques generados correctamente")

    # archivar duplicados
    if not args.no_move:
        movidos = archivar_duplicados(src, args.dry_run)
        if movidos:
            log.info("")
            verbo = "se moverían" if args.dry_run else "movidos"
            log.info(f"  Duplicados antiguos {verbo} a _procesados: {len(movidos)}")
            for m in movidos:
                log.info(f"    · {m}")

    log.info("=" * 74)
    # nota de aviso si algún bloque salió OK* (dato viejo) o falló
    problemas = [r for r in resultados if r.estado not in ("OK",)]
    if problemas:
        log.info("  AVISOS:")
        for r in problemas:
            log.info(f"    · {r.nombre}: {r.estado} {('- ' + r.aviso) if r.aviso else ''}")
    log.info("  Listo. Ahora puedes ejecutar:  python actualizar_radar.py")
    log.info("=" * 74)


if __name__ == "__main__":
    main()
