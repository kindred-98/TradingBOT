"""
Modelo de clasificación de señales.

En vez de reglas fijas ("si EMA cruza, compra"), el modelo aprende de datos
históricos en qué CONTEXTO esas mismas señales sí anticiparon movimiento
a favor. Esto es lo que te falta hoy operando manualmente: capturar
combinaciones (ej. "ema_cross=1 + volume_ratio>1.5 + rsi<70 en H1") que a
ojo no se detectan de forma consistente.

Instalación: pip install xgboost scikit-learn pandas joblib
"""

import pandas as pd
import numpy as np
import joblib
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

FEATURE_COLS = [
    "ema_cross", "above_trend", "volume_ratio", "atr", "rsi",
    "MACD_12_26_9", "MACDh_12_26_9", "MACDs_12_26_9",
    "body_pct", "bullish_engulfing", "bearish_engulfing",
]


def make_labels(df: pd.DataFrame, horizon: int = 4, threshold_atr_mult: float = 1.0) -> pd.DataFrame:
    """
    Etiqueta cada vela como 1 (señal válida de compra), -1 (venta) o 0 (no operar),
    según si el precio se movió a favor al menos `threshold_atr_mult` * ATR
    en las próximas `horizon` velas, ANTES de moverse en contra esa misma
    distancia (evita etiquetar como "ganadora" una entrada que primero
    te hubiera sacado por stop).

    horizon en velas de tu timeframe primario (H1 por defecto -> 4 = 4 horas).
    """
    out = df.copy()
    future_max = out["high"].shift(-1).rolling(horizon).max().shift(-(horizon - 1))
    future_min = out["low"].shift(-1).rolling(horizon).min().shift(-(horizon - 1))

    up_move = future_max - out["close"]
    down_move = out["close"] - future_min
    threshold = out["atr"] * threshold_atr_mult

    label = np.where(
        up_move >= threshold, 1,
        np.where(down_move >= threshold, -1, 0)
    )
    out["label"] = label
    return out.dropna().reset_index(drop=True)


def train(df_labeled: pd.DataFrame, model_path: str = "models/signal_model.joblib"):
    """
    Entrena el clasificador. IMPORTANTE: usa split temporal (no aleatorio) —
    en series de tiempo, mezclar al azar filtra información del futuro
    (data leakage) y te da métricas falsamente buenas.
    """
    X = df_labeled[FEATURE_COLS]
    y = df_labeled["label"]

    split_idx = int(len(df_labeled) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="mlogloss",
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    print("=== Evaluación out-of-sample (datos que el modelo NO vio) ===")
    print(classification_report(y_test, preds))

    joblib.dump(model, model_path)
    print(f"Modelo guardado en {model_path}")
    return model


def predict_signal(model, features_row: pd.Series, min_confidence: float = 0.60) -> dict:
    """
    Devuelve la señal para la vela más reciente, o None si la confianza
    del modelo no supera el umbral configurado (mejor no operar que
    forzar una señal débil).
    """
    X = features_row[FEATURE_COLS].values.reshape(1, -1)
    proba = model.predict_proba(X)[0]
    pred_class = model.classes_[np.argmax(proba)]
    confidence = np.max(proba)

    if confidence < min_confidence or pred_class == 0:
        return {"signal": None, "confidence": float(confidence)}

    return {
        "signal": "BUY" if pred_class == 1 else "SELL",
        "confidence": float(confidence),
    }
