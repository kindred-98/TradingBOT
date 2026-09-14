"""
Backtesting con validación walk-forward: en vez de un único split
train/test, entrena y valida en ventanas móviles sucesivas. Esto es
crucial para no engañarte con un backtest que solo funcionó por
casualidad en un periodo específico del mercado.

Instalación: pip install vectorbt pandas numpy
"""

import pandas as pd
import numpy as np

from src.features.indicators import build_features
from src.signals.model import make_labels, train, predict_signal, FEATURE_COLS


def walk_forward_backtest(
    raw_df: pd.DataFrame, cfg: dict, n_windows: int = 5,
    train_pct: float = 0.7,
) -> pd.DataFrame:
    """
    Divide los datos en n_windows ventanas. En cada una: entrena con
    train_pct de la ventana, evalúa en el resto. Así ves si el modelo
    generaliza en distintos regímenes de mercado, no solo en uno.
    """
    df = build_features(raw_df, cfg["signals"]["indicators"])
    df = make_labels(df, horizon=4, threshold_atr_mult=1.0)

    window_size = len(df) // n_windows
    results = []

    for w in range(n_windows):
        start = w * window_size
        end = start + window_size
        window = df.iloc[start:end].reset_index(drop=True)

        split = int(len(window) * train_pct)
        train_df, test_df = window.iloc[:split], window.iloc[split:]

        if len(train_df) < 50 or len(test_df) < 10:
            continue

        model = train(train_df, model_path=f"models/wf_model_{w}.joblib")

        wins, losses, no_trade = 0, 0, 0
        for _, row in test_df.iterrows():
            result = predict_signal(model, row, cfg["signals"]["min_confidence"])
            if result["signal"] is None:
                no_trade += 1
                continue
            correct = (
                (result["signal"] == "BUY" and row["label"] == 1) or
                (result["signal"] == "SELL" and row["label"] == -1)
            )
            wins += int(correct)
            losses += int(not correct)

        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0
        results.append({
            "window": w, "trades": total_trades, "wins": wins,
            "losses": losses, "win_rate": round(win_rate, 3),
            "no_trade_bars": no_trade,
        })

    results_df = pd.DataFrame(results)
    print(results_df)
    print(f"\nWin rate promedio entre ventanas: {results_df['win_rate'].mean():.2%}")
    print(
        "Si el win rate varía mucho entre ventanas, el modelo no es "
        "consistente entre regímenes de mercado — no lo lleves a cuenta real todavía."
    )
    return results_df
