"""
Motor de features: convierte velas OHLCV en las señales que ya usas
manualmente (EMA, SMA, volumen, patrones de vela) + features derivados
para que el modelo de ML tenga con qué aprender combinaciones no lineales.

Instalación: pip install pandas-ta pandas numpy
"""

import pandas as pd
import pandas_ta as ta


def build_features(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    df: DataFrame con columnas [time, open, high, low, close, volume]
    cfg: sub-diccionario config['signals']['indicators']
    """
    out = df.copy()

    # --- Medias móviles / exponenciales (tus señales actuales) ---
    out["ema_fast"] = ta.ema(out["close"], length=cfg["ema_fast"])
    out["ema_slow"] = ta.ema(out["close"], length=cfg["ema_slow"])
    out["sma_trend"] = ta.sma(out["close"], length=cfg["sma_trend"])

    out["ema_cross"] = (out["ema_fast"] > out["ema_slow"]).astype(int)
    out["above_trend"] = (out["close"] > out["sma_trend"]).astype(int)

    # --- Volumen relativo (no el volumen absoluto, sino contra su promedio) ---
    out["volume_avg"] = out["volume"].rolling(cfg["volume_lookback"]).mean()
    out["volume_ratio"] = out["volume"] / out["volume_avg"]

    # --- Volatilidad (ATR) — clave para el sizing del Risk Manager ---
    out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=14)

    # --- Momentum / osciladores como contexto adicional ---
    out["rsi"] = ta.rsi(out["close"], length=14)
    macd = ta.macd(out["close"])
    out = pd.concat([out, macd], axis=1)

    # --- Patrones de vela (usa el catálogo de pandas-ta / ta-lib) ---
    out["body"] = out["close"] - out["open"]
    out["range"] = out["high"] - out["low"]
    out["body_pct"] = (out["body"].abs() / out["range"].replace(0, pd.NA)).fillna(0)
    out["bullish_engulfing"] = _bullish_engulfing(out)
    out["bearish_engulfing"] = _bearish_engulfing(out)

    return out.dropna().reset_index(drop=True)


def _bullish_engulfing(df: pd.DataFrame) -> pd.Series:
    prev_bear = df["close"].shift(1) < df["open"].shift(1)
    curr_bull = df["close"] > df["open"]
    engulf = (df["close"] > df["open"].shift(1)) & (df["open"] < df["close"].shift(1))
    return (prev_bear & curr_bull & engulf).astype(int)


def _bearish_engulfing(df: pd.DataFrame) -> pd.Series:
    prev_bull = df["close"].shift(1) > df["open"].shift(1)
    curr_bear = df["close"] < df["open"]
    engulf = (df["close"] < df["open"].shift(1)) & (df["open"] > df["close"].shift(1))
    return (prev_bull & curr_bear & engulf).astype(int)
