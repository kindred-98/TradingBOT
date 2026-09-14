"""
Backtesting con validación walk-forward: en vez de un único split
train/test, entrena y valida en ventanas móviles sucesivas. Esto es
crucial para no engañarte con un backtest que solo funcionó por
casualidad en un periodo específico del mercado.

Desde trading_bot/: python src/backtest/run_backtest.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.data.mt5_connector import MT5Connector
from src.features.indicators import build_features
from src.signals.model import make_labels, train, predict_signal
from src.storage.db import TradingDB


def walk_forward_backtest(
    raw_df: pd.DataFrame, cfg: dict, n_windows: int = 5,
    train_pct: float = 0.7,
) -> pd.DataFrame:
    """
    Divide los datos en n_windows ventanas. En cada una: entrena con
    train_pct de la ventana, evalúa en el resto. Así ves si el modelo
    generaliza en distintos regímenes de mercado, no solo en uno.
    """
    Path("models").mkdir(exist_ok=True)

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
    if results_df.empty:
        print("Sin ventanas válidas (pocos datos).")
        return results_df
    print(f"\nWin rate promedio entre ventanas: {results_df['win_rate'].mean():.2%}")
    print(
        "Si el win rate varía mucho entre ventanas, el modelo no es "
        "consistente entre regímenes de mercado — no lo lleves a cuenta real todavía."
    )
    return results_df


def main():
    load_dotenv(_ROOT / ".env")
    os.chdir(_ROOT)

    with open("config/config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    n_windows = 5
    train_pct = 0.7
    n_bars = 5000
    tf = cfg["timeframes"]["primary"]

    mt5_conn = MT5Connector(
        login=int(os.getenv("MT5_LOGIN", 0)),
        password=os.getenv("MT5_PASSWORD", ""),
        server=os.getenv("MT5_SERVER", ""),
    )
    mt5_conn.connect()
    db = TradingDB()

    try:
        for symbol in cfg["symbols"]:
            print(f"\n=== Walk-forward {symbol} {tf} ===")
            raw = mt5_conn.get_historical_data(symbol, tf, n_bars=n_bars)
            results_df = walk_forward_backtest(
                raw, cfg, n_windows=n_windows, train_pct=train_pct,
            )
            if results_df.empty:
                continue
            run_id = db.log_backtest_run(
                n_windows=n_windows,
                train_pct=train_pct,
                windows=results_df.to_dict("records"),
                symbol=symbol,
            )
            print(f"Guardado en SQLite (run_id={run_id})")
    finally:
        db.close()
        mt5_conn.disconnect()


if __name__ == "__main__":
    main()
