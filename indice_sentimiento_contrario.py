"""
╔══════════════════════════════════════════════════════════════════════════╗
║  indice_sentimiento_contrario.py — Oscilador compuesto -100/+100        ║
║  NQ UNIFIED · Parte 1.2 de IDEAS_FUTURAS_NQ_UNIFIED.md                   ║
╠══════════════════════════════════════════════════════════════════════════╣
║  Combina 4 señales contrarian ya validadas de verdad con                ║
║  validar_factor.py (ver sesión 05/07/2026), ponderadas por |IC| medido  ║
║  a 20 días sobre historico_maestro.csv (2000-2026):                    ║
║                                                                          ║
║     DIX (dark pool)........... peso 0.297   (directo)                  ║
║     VTS ratio (VIX3M/VIX)..... peso 0.258   (invertido)                ║
║     VVIX/VIX.................. peso 0.247   (invertido)                ║
║     COT leveraged net %il..... peso 0.198   (invertido)                ║
║                                                                          ║
║  PCR se dejó FUERA: no pasó validación (IC=0.015, WF 1/4 a 20d),        ║
║  igual que le ocurrió a NRA-DAS de forma independiente. Muestra         ║
║  corta (solo 2019-2026), revisar cuando haya más histórico.            ║
║                                                                          ║
║  RESULTADO DEL PROPIO COMPUESTO (validado con validar_factor.py,       ║
║  no solo sus piezas por separado):                                     ║
║                                                                          ║
║     Horizonte   IC      Stability   Walk-Forward   Aprobado            ║
║       5 días   0.070      100%         3/4            SI               ║
║      20 días   0.133      100%         4/4            SI               ║
║      60 días   0.162      100%         4/4            SI               ║
║                                                                          ║
║  El compuesto SUPERA a cada pieza individual en todos los horizontes   ║
║  (DIX solo: 0.129 a 20d / 0.119 a 60d). Diversificar señal de          ║
║  sentimiento da lectura más limpia que cualquier fuente suelta.        ║
║                                                                          ║
║  IMPORTANTE — hallazgo de la sesión: VTS y VVIX/VIX se orientan        ║
║  INVERTIDOS respecto a como Manengis trata hoy la backwardation        ║
║  (ahí suma riesgo; aquí backwardation = contrarian alcista). No son    ║
║  contradictorios — el Módulo de Deterioro gestiona drawdown con        ║
║  histéresis, este índice mide oportunidad de rebote — pero conviene    ║
║  tenerlo presente al decidir cómo se combinan ambos en el futuro.      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import numpy as np
import pandas as pd


PESOS_DEFECTO = {"dix": 0.297, "vts": 0.258, "vvix": 0.247, "cot": 0.198}


def _percentil_expanding(serie: pd.Series, min_periodos: int = 60) -> pd.Series:
    """Percentil 0-100 de cada valor dentro de TODO lo visto hasta esa fecha
    (expanding, sin fuga de información futura). Es la versión sin look-ahead
    de _csv_percentil() ya usada en actualizar_radar.py."""
    vals = serie.values
    out = np.full(len(vals), np.nan)
    idx_validos = np.where(~np.isnan(vals))[0]
    for pos, i in enumerate(idx_validos):
        if pos + 1 < min_periodos:
            continue
        ventana = vals[idx_validos[: pos + 1]]
        out[i] = (ventana <= vals[i]).mean() * 100
    return pd.Series(out, index=serie.index)


def calcular_indice_contrario(
    dix: pd.Series,
    vts_ratio: pd.Series,
    vvix_vix_ratio: pd.Series,
    cot_lev_pctl: pd.Series,
    pesos: dict | None = None,
    min_periodos: int = 60,
) -> pd.Series:
    """
    Construye el oscilador -100 (extremo pesimismo → contrarian bajista)
    a +100 (extremo optimismo → contrarian alcista).

    Todas las series deben venir ya alineadas por fecha (mismo índice
    que se quiera usar, típicamente el de historico_maestro.csv).
    cot_lev_pctl se espera YA como percentil 0-100 (así se calcula hoy
    en producción, semanal reindexado a diario con ffill).

    Si algún día falta una pieza, se renormalizan los pesos entre las
    piezas disponibles ese día en vez de romper o dar NaN innecesario.
    """
    pesos = dict(pesos or PESOS_DEFECTO)

    pctl_dix = _percentil_expanding(dix, min_periodos)
    pctl_vts = _percentil_expanding(vts_ratio, min_periodos)
    pctl_vvix = _percentil_expanding(vvix_vix_ratio, min_periodos)

    score_dix = pctl_dix                    # directo: más DIX = más contrarian alcista
    score_vts = 100 - pctl_vts              # invertido: backwardation (pctl bajo) = alcista
    score_vvix = 100 - pctl_vvix            # invertido: mismo motivo
    score_cot = 100 - cot_lev_pctl          # invertido: crowding largo = contrarian bajista

    componentes = pd.concat(
        [score_dix.rename("dix"), score_vts.rename("vts"),
         score_vvix.rename("vvix"), score_cot.rename("cot")],
        axis=1,
    )

    def _combinar(fila: pd.Series) -> float:
        disponibles = fila.dropna()
        if disponibles.empty:
            return np.nan
        w = np.array([pesos[k] for k in disponibles.index])
        w = w / w.sum()
        return float((disponibles.values * w).sum())

    media_ponderada = componentes.apply(_combinar, axis=1)
    indice = (media_ponderada - 50) * 2
    indice.name = "indice_sentimiento_contrario"
    return indice


def interpretar(valor: float) -> str:
    """Traducción cualitativa del valor del índice, para mostrar en el panel."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)):
        return "Sin datos suficientes"
    if valor >= 50:
        return "Miedo extremo — zona contrarian alcista fuerte"
    if valor >= 20:
        return "Cautela de mercado — sesgo contrarian alcista"
    if valor > -20:
        return "Neutral"
    if valor > -50:
        return "Complacencia — sesgo contrarian bajista"
    return "Complacencia extrema — zona contrarian bajista fuerte"


if __name__ == "__main__":
    # Prueba rápida de humo con datos de ejemplo (no sustituye a la validación
    # real ya hecha contra historico_maestro.csv en la sesión de diseño).
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    rng = np.random.default_rng(0)
    ejemplo = calcular_indice_contrario(
        dix=pd.Series(rng.uniform(0.35, 0.50, 300), index=idx),
        vts_ratio=pd.Series(rng.uniform(0.9, 1.3, 300), index=idx),
        vvix_vix_ratio=pd.Series(rng.uniform(4, 7, 300), index=idx),
        cot_lev_pctl=pd.Series(rng.uniform(0, 100, 300), index=idx),
    )
    print(ejemplo.tail())
    print(interpretar(ejemplo.iloc[-1]))
