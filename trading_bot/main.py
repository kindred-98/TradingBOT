"""
Punto de entrada. Pipeline en vivo:

  MT5 (datos) -> features -> modelo -> Risk Manager -> alerta/ejecución

Corre esto en loop (ej. cada vez que cierra una vela H1) o prográmalo
con un scheduler (APScheduler) para no tener que dejarlo corriendo
manualmente en terminal.
"""

import os
import time
import yaml
import joblib
from datetime import date
from dotenv import load_dotenv

from src.data.mt5_connector import MT5Connector
from src.features.indicators import build_features
from src.signals.model import predict_signal, FEATURE_COLS
from src.risk.risk_manager import RiskManager, RiskState
from src.alerts.telegram_alert import TelegramAlerter, send_alert_sync
from src.storage.db import TradingDB

load_dotenv()


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def run_once(cfg: dict, mt5_conn: MT5Connector, model, risk_mgr: RiskManager,
             alerter: TelegramAlerter, initial_balance: float, db: TradingDB):
    account = mt5_conn.get_account_info()
    trade_date = date.today()
    try:
        opening = mt5_conn.get_day_opening_balance()
        db.upsert_daily_open(trade_date.isoformat(), opening)
    except RuntimeError as exc:
        stored = db.get_daily_open(trade_date.isoformat())
        if stored is None:
            raise RuntimeError(
                f"No se pudo obtener el balance de apertura del día: {exc}"
            ) from exc
        opening = stored
        print(f"MT5 no dio el open del día; se usa el guardado ({opening})")

    positions = mt5_conn.get_open_positions()

    state = RiskState(
        starting_balance_today=opening,
        current_equity=account["equity"],
        initial_balance=initial_balance,
        open_positions=len(positions),
        trade_date=trade_date,
    )

    allowed, reason = risk_mgr.can_open_trade(state)
    db.log_risk_snapshot(
        starting_balance_today=state.starting_balance_today,
        current_equity=state.current_equity,
        initial_balance=state.initial_balance,
        open_positions=state.open_positions,
        daily_loss_pct=risk_mgr.daily_loss_pct(state),
        total_drawdown_pct=risk_mgr.total_drawdown_pct(state),
        can_trade=allowed,
        reason=reason,
    )
    if not allowed:
        print(reason)
        if cfg["alerts"]["telegram_enabled"]:
            import asyncio
            asyncio.run(alerter.send_risk_block(reason))
        return

    for symbol in cfg["symbols"]:
        raw = mt5_conn.get_historical_data(
            symbol, cfg["timeframes"]["primary"], n_bars=300
        )
        features = build_features(raw, cfg["signals"]["indicators"])
        last_row = features.iloc[-1]

        result = predict_signal(model, last_row, cfg["signals"]["min_confidence"])
        if result["signal"] is None:
            continue

        live = mt5_conn.get_live_price(symbol)
        if live is None:
            print(f"[{symbol}] sin precio en vivo, se omite")
            continue
        entry = live["ask"] if result["signal"] == "BUY" else live["bid"]
        atr = last_row["atr"]
        sl = entry - atr * 1.5 if result["signal"] == "BUY" else entry + atr * 1.5
        tp = entry + atr * 3 if result["signal"] == "BUY" else entry - atr * 3

        t = last_row["time"] if "time" in last_row.index else None
        bar_time = t.isoformat() if hasattr(t, "isoformat") else (str(t) if t is not None else None)
        db.log_signal(
            symbol=symbol,
            timeframe=cfg["timeframes"]["primary"],
            signal=result["signal"],
            confidence=result["confidence"],
            entry=round(entry, 5),
            sl=round(sl, 5),
            tp=round(tp, 5),
            atr=float(atr),
            bar_time=bar_time,
        )

        print(f"[{symbol}] Señal: {result['signal']} (confianza {result['confidence']:.0%})")

        if cfg["execution"]["mode"] == "alert_only":
            if cfg["alerts"]["telegram_enabled"]:
                send_alert_sync(
                    alerter, symbol, result["signal"], result["confidence"],
                    round(entry, 5), round(sl, 5), round(tp, 5),
                    cfg["timeframes"]["primary"],
                )
        elif cfg["execution"]["mode"] == "auto":
            # TODO: implementar mt5.order_send() aquí, SOLO después de validar
            # con track record real en modo alert_only durante semanas.
            raise NotImplementedError(
                "Ejecución automática deshabilitada a propósito. "
                "Valida primero con modo alert_only."
            )


def main():
    cfg = load_config()

    mt5_conn = MT5Connector(
        login=int(os.getenv("MT5_LOGIN", 0)),
        password=os.getenv("MT5_PASSWORD", ""),
        server=os.getenv("MT5_SERVER", ""),
    )
    mt5_conn.connect()

    model = joblib.load("models/signal_model.joblib")  # entrena primero con backtest

    risk_mgr = RiskManager(cfg)
    alerter = TelegramAlerter(
        token=os.getenv("TELEGRAM_TOKEN", ""),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
    )

    initial_balance = float(os.getenv("ACCOUNT_INITIAL_BALANCE", 0))
    db = TradingDB()

    try:
        while True:
            run_once(cfg, mt5_conn, model, risk_mgr, alerter, initial_balance, db)
            time.sleep(3600)  # H1: revisa cada hora al cierre de vela
    except KeyboardInterrupt:
        print("Detenido manualmente.")
    finally:
        db.close()
        mt5_conn.disconnect()


if __name__ == "__main__":
    main()
