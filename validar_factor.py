"""
╔══════════════════════════════════════════════════════════════════════════╗
║  validar_factor.py — Banco de pruebas IC/Stability/Walk-Forward          ║
║  NQ UNIFIED · Parte 0 de IDEAS_FUTURAS_NQ_UNIFIED.md                     ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Objetivo: antes de dejar que un factor (PCR, COT, VIX Term Structure,  ║
║  SKEW, DIX...) pese en el score, medir si REALMENTE predice el retorno  ║
║  futuro de NDX, con el mismo criterio que usa NRA-DAS:                  ║
║                                                                          ║
║      |IC| > 0.03  AND  p < 0.05  AND  Stability >= 70%  AND  WF >= 3/4  ║
║                                                                          ║
║  IC = Information Coefficient = correlación de Spearman entre el valor  ║
║  del factor en t y el retorno futuro de NDX a N días (default 20).      ║
║                                                                          ║
║  ESTADO: escrito pero NO EJECUTADO contra datos reales todavía —        ║
║  pendiente de recibir historico_maestro.csv. No subir a producción      ║
║  ni fiarse de ningún resultado hasta correrlo de verdad (regla del      ║
║  proyecto: siempre ejecución real, nunca solo compilación).             ║
╚══════════════════════════════════════════════════════════════════════════╝

Uso previsto:

    from validar_factor import validar_factor
    import pandas as pd

    hm = pd.read_csv("historico_maestro.csv", index_col=0, parse_dates=True)

    resultado = validar_factor(
        serie_factor=hm["algun_factor_ya_alineado_a_hm.index"],
        precios_ndx=hm["NDX_close"],
        nombre="PCR_total",
        horizonte=20,
    )
    print(resultado)

O desde línea de comandos (una vez definidas las columnas reales):

    python validar_factor.py --factor PCR_total --horizonte 20
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


# ─────────────────────────────────────────────────────────────────────────
#  RESULTADO ESTRUCTURADO
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class ResultadoValidacion:
    nombre: str
    horizonte_dias: int
    n_obs: int
    ic: float | None
    p_value: float | None
    stability_pct: float | None
    walkforward_pass: int | None
    walkforward_total: int
    ic_por_subventana: list | None
    signo_global: str | None
    aprobado: bool
    motivo: str


# ─────────────────────────────────────────────────────────────────────────
#  NÚCLEO: IC (Information Coefficient)
# ─────────────────────────────────────────────────────────────────────────

def _retorno_futuro(precios: pd.Series, horizonte: int) -> pd.Series:
    """Retorno porcentual de NDX entre t y t+horizonte (shift hacia atrás
    para que el retorno quede alineado con la fecha t del factor)."""
    return precios.shift(-horizonte) / precios - 1.0


def _ic_spearman(factor: pd.Series, retorno_fwd: pd.Series) -> tuple[float | None, float | None, int]:
    """Spearman entre factor y retorno futuro, alineados por fecha,
    descartando NaN. Devuelve (ic, p_value, n_obs)."""
    df = pd.concat([factor.rename("f"), retorno_fwd.rename("r")], axis=1).dropna()
    n = len(df)
    if n < 60:
        return None, None, n
    ic, p = stats.spearmanr(df["f"], df["r"])
    return float(ic), float(p), n


def _dividir_df(df: pd.DataFrame, n_partes: int) -> list[pd.DataFrame]:
    """Partición cronológica en n_partes bloques lo más iguales posible,
    usando iloc (np.array_split convierte el DataFrame en ndarray en
    algunas combinaciones de versiones de numpy/pandas y rompe el acceso
    por columna — se descubrió ejecutando este módulo con datos reales,
    no solo compilándolo)."""
    n = len(df)
    tam = n // n_partes
    resto = n % n_partes
    bloques = []
    inicio = 0
    for i in range(n_partes):
        extra = 1 if i < resto else 0
        fin = inicio + tam + extra
        bloques.append(df.iloc[inicio:fin])
        inicio = fin
    return bloques


# ─────────────────────────────────────────────────────────────────────────
#  STABILITY — consistencia de signo en sub-ventanas
# ─────────────────────────────────────────────────────────────────────────

def _stability(factor: pd.Series, retorno_fwd: pd.Series, ic_global: float,
                n_subventanas: int = 4) -> tuple[float | None, list]:
    df = pd.concat([factor.rename("f"), retorno_fwd.rename("r")], axis=1).dropna()
    if len(df) < 60 * n_subventanas:
        return None, []

    signo_global = np.sign(ic_global)
    cortes = _dividir_df(df, n_subventanas)
    ics_sub = []
    aciertos = 0
    for bloque in cortes:
        if len(bloque) < 20:
            ics_sub.append(None)
            continue
        ic_b, _ = stats.spearmanr(bloque["f"], bloque["r"])
        ics_sub.append(round(float(ic_b), 4))
        if np.sign(ic_b) == signo_global and signo_global != 0:
            aciertos += 1

    validos = [x for x in ics_sub if x is not None]
    if not validos:
        return None, ics_sub
    stability_pct = round(100 * aciertos / len(validos), 1)
    return stability_pct, ics_sub


# ─────────────────────────────────────────────────────────────────────────
#  WALK-FORWARD — validación cronológica fuera de muestra
# ─────────────────────────────────────────────────────────────────────────

def _walkforward(factor: pd.Series, retorno_fwd: pd.Series,
                  n_tramos: int = 4) -> tuple[int | None, int]:
    """
    Divide la serie en n_tramos+1 bloques cronológicos consecutivos.
    En cada paso k: calcula el signo del IC "in-sample" con todo lo
    disponible hasta el final del bloque k, y comprueba si ese MISMO
    signo se mantiene en el bloque k+1 (fuera de muestra, nunca visto
    en el cálculo). Cuenta cuántos de los n_tramos pasos mantienen el
    signo. Esto es deliberadamente estricto: no reoptimiza ningún
    parámetro, solo verifica persistencia direccional real.
    """
    df = pd.concat([factor.rename("f"), retorno_fwd.rename("r")], axis=1).dropna()
    if len(df) < 60 * (n_tramos + 1):
        return None, n_tramos

    bloques = _dividir_df(df, n_tramos + 1)
    aciertos = 0
    comparables = 0
    acumulado = bloques[0]
    for k in range(n_tramos):
        siguiente = bloques[k + 1]
        if len(acumulado) < 30 or len(siguiente) < 20:
            acumulado = pd.concat([acumulado, siguiente])
            continue
        ic_in, _ = stats.spearmanr(acumulado["f"], acumulado["r"])
        ic_out, _ = stats.spearmanr(siguiente["f"], siguiente["r"])
        comparables += 1
        if np.sign(ic_in) == np.sign(ic_out) and np.sign(ic_in) != 0:
            aciertos += 1
        acumulado = pd.concat([acumulado, siguiente])

    if comparables == 0:
        return None, n_tramos
    return aciertos, comparables


# ─────────────────────────────────────────────────────────────────────────
#  FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────

def validar_factor(serie_factor: pd.Series, precios_ndx: pd.Series,
                    nombre: str = "factor", horizonte: int = 20,
                    ic_min: float = 0.03, p_max: float = 0.05,
                    stability_min: float = 70.0,
                    wf_min_fraccion: float = 0.75) -> ResultadoValidacion:
    """
    Valida un factor contra el retorno futuro de NDX con el criterio de
    NRA-DAS: |IC|>ic_min, p<p_max, stability>=stability_min,
    walkforward>=wf_min_fraccion.

    serie_factor y precios_ndx deben venir YA alineados por fecha
    (mismo índice, o al menos indexables por fecha — el merge interno
    hace el align real).
    """
    retorno_fwd = _retorno_futuro(precios_ndx, horizonte)
    ic, p_value, n_obs = _ic_spearman(serie_factor, retorno_fwd)

    if ic is None:
        return ResultadoValidacion(
            nombre=nombre, horizonte_dias=horizonte, n_obs=n_obs,
            ic=None, p_value=None, stability_pct=None,
            walkforward_pass=None, walkforward_total=0,
            ic_por_subventana=None, signo_global=None,
            aprobado=False, motivo=f"Datos insuficientes tras alinear (n={n_obs}, mínimo 60)."
        )

    stability_pct, ics_sub = _stability(serie_factor, retorno_fwd, ic)
    wf_pass, wf_total = _walkforward(serie_factor, retorno_fwd)

    signo_global = "alcista" if ic > 0 else "bajista" if ic < 0 else "neutro"

    cumple_ic = abs(ic) > ic_min
    cumple_p = p_value is not None and p_value < p_max
    cumple_stab = stability_pct is not None and stability_pct >= stability_min
    cumple_wf = (wf_pass is not None and wf_total > 0
                 and (wf_pass / wf_total) >= wf_min_fraccion)

    aprobado = cumple_ic and cumple_p and cumple_stab and cumple_wf

    razones_fallo = []
    if not cumple_ic:   razones_fallo.append(f"|IC|={abs(ic):.3f} <= {ic_min}")
    if not cumple_p:    razones_fallo.append(f"p={p_value:.3f} >= {p_max}" if p_value is not None else "p no calculable")
    if not cumple_stab: razones_fallo.append(f"Stability={stability_pct} < {stability_min}%" if stability_pct is not None else "Stability no calculable")
    if not cumple_wf:   razones_fallo.append(f"WF={wf_pass}/{wf_total} < {wf_min_fraccion*100:.0f}%" if wf_pass is not None else "WF no calculable")

    motivo = "Cumple los 4 criterios." if aprobado else "No cumple: " + "; ".join(razones_fallo)

    return ResultadoValidacion(
        nombre=nombre, horizonte_dias=horizonte, n_obs=n_obs,
        ic=round(ic, 4), p_value=round(p_value, 4) if p_value is not None else None,
        stability_pct=stability_pct,
        walkforward_pass=wf_pass, walkforward_total=wf_total,
        ic_por_subventana=ics_sub, signo_global=signo_global,
        aprobado=aprobado, motivo=motivo,
    )


def validar_multiples(factores: dict[str, pd.Series], precios_ndx: pd.Series,
                       horizonte: int = 20) -> pd.DataFrame:
    """Conveniencia: valida un dict {nombre: serie} y devuelve una tabla
    ordenada por |IC| descendente, lista para pegar en el chat o exportar."""
    filas = []
    for nombre, serie in factores.items():
        r = validar_factor(serie, precios_ndx, nombre=nombre, horizonte=horizonte)
        filas.append(asdict(r))
    df = pd.DataFrame(filas)
    df["abs_ic"] = df["ic"].abs()
    return df.sort_values("abs_ic", ascending=False).drop(columns="abs_ic")


# ─────────────────────────────────────────────────────────────────────────
#  CLI (para cuando tengamos historico_maestro.csv + columnas reales)
# ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Valida factores de NQ Unified con criterio IC/Stability/WF")
    ap.add_argument("--historico", default="historico_maestro.csv",
                     help="Ruta al historico_maestro.csv")
    ap.add_argument("--horizonte", type=int, default=20,
                     help="Horizonte de retorno futuro en días de trading (default 20)")
    ap.add_argument("--columna-precio", default="NDX_close",
                     help="Columna de precio contra la que medir retorno futuro")
    ap.add_argument("--factores", nargs="+", required=True,
                     help="Nombres de columnas de historico_maestro.csv a validar como factores")
    args = ap.parse_args()

    ruta = Path(args.historico)
    if not ruta.exists():
        raise SystemExit(f"No encuentro {ruta}. Pásalo con --historico ruta/al/archivo.csv")

    hm = pd.read_csv(ruta, index_col=0, parse_dates=True)
    if args.columna_precio not in hm.columns:
        raise SystemExit(f"Columna de precio '{args.columna_precio}' no existe en {ruta}. "
                          f"Columnas disponibles: {list(hm.columns)}")

    factores = {}
    for col in args.factores:
        if col not in hm.columns:
            print(f"[AVISO] Columna '{col}' no existe, se omite.")
            continue
        factores[col] = hm[col]

    if not factores:
        raise SystemExit("Ninguna de las columnas pedidas existe en el CSV.")

    tabla = validar_multiples(factores, hm[args.columna_precio], horizonte=args.horizonte)
    print(tabla.to_string(index=False))
    print()
    print(json.dumps(tabla.to_dict(orient="records"), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
