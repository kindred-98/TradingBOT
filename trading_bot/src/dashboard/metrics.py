"""
Agrega al dashboard números que se pueden leer de un vistazo:
headroom de riesgo, consistencia del walk-forward, curva teórica en R.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import pstdev
from typing import Optional


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: Optional[str]) -> Optional[int]:
    ts = _parse_ts(value)
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - ts).total_seconds()))


def _zone(value: float, halt_at: float) -> str:
    if value >= halt_at:
        return "blocked"
    if halt_at > 0 and value >= halt_at * 0.6:
        return "warning"
    return "ok"


def _meter(value: float, halt_at: float, hard_limit: float) -> dict:
    ceiling = hard_limit if hard_limit > 0 else 1.0
    return {
        "value": round(value, 3),
        "halt_at": round(halt_at, 3),
        "hard_limit": round(hard_limit, 3),
        "headroom": round(max(0.0, halt_at - value), 3),
        "utilization": round(min(1.0, value / ceiling), 4),
        "zone": _zone(value, halt_at),
    }


def _streak(statuses: list[str]) -> dict:
    consecutive_wins = 0
    consecutive_losses = 0
    max_wins = 0
    max_losses = 0
    for status in statuses:
        if status == "win":
            consecutive_wins += 1
            consecutive_losses = 0
        elif status == "loss":
            consecutive_losses += 1
            consecutive_wins = 0
        else:
            continue
        max_wins = max(max_wins, consecutive_wins)
        max_losses = max(max_losses, consecutive_losses)
    current = {"side": None, "count": 0}
    if consecutive_wins:
        current = {"side": "win", "count": consecutive_wins}
    elif consecutive_losses:
        current = {"side": "loss", "count": consecutive_losses}
    return {
        "current": current,
        "max_wins": max_wins,
        "max_losses": max_losses,
    }


def _live_equity(signals: list[dict]) -> list[dict]:
    closed = [
        s for s in reversed(signals)
        if s.get("status") in ("win", "loss")
    ]
    points = []
    equity = 0.0
    for item in closed:
        pnl = item.get("pnl")
        if pnl is None:
            pnl = 1.0 if item["status"] == "win" else -1.0
        equity += float(pnl)
        points.append({
            "t": item.get("closed_at") or item.get("created_at"),
            "v": round(equity, 2),
            "symbol": item.get("symbol"),
            "status": item.get("status"),
        })
    return points


def _by_symbol(signals: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for item in signals:
        symbol = item.get("symbol") or "?"
        bucket = buckets.setdefault(symbol, {"symbol": symbol, "total": 0, "wins": 0, "losses": 0, "pending": 0})
        bucket["total"] += 1
        if item["status"] == "win":
            bucket["wins"] += 1
        elif item["status"] == "loss":
            bucket["losses"] += 1
        elif item["status"] == "pending":
            bucket["pending"] += 1
    out = []
    for bucket in buckets.values():
        closed = bucket["wins"] + bucket["losses"]
        bucket["win_rate"] = round(bucket["wins"] / closed, 3) if closed else None
        out.append(bucket)
    out.sort(key=lambda x: x["symbol"])
    return out


def _backtest_view(run: Optional[dict]) -> Optional[dict]:
    if not run:
        return None
    windows = run.get("windows") or []
    rates = [float(w["win_rate"]) for w in windows]
    equity = [{"t": -1, "v": 0.0}]
    r_multiple = 0.0
    for w in windows:
        r_multiple += int(w["wins"]) - int(w["losses"])
        equity.append({"t": int(w["window"]), "v": float(r_multiple)})
    spread = (max(rates) - min(rates)) if rates else 0.0
    consistency = "ok"
    if not rates:
        consistency = "empty"
    elif spread >= 0.25:
        consistency = "unstable"
    elif spread >= 0.15:
        consistency = "watch"
    return {
        **run,
        "spread": round(spread, 3),
        "stdev": round(pstdev(rates), 3) if len(rates) > 1 else 0.0,
        "consistency": consistency,
        "equity_r": equity,
        "min_win_rate": round(min(rates), 3) if rates else None,
        "max_win_rate": round(max(rates), 3) if rates else None,
    }


def build_overview(db, cfg: dict) -> dict:
    rm = cfg["risk_management"]
    daily_limit = float(rm["max_daily_loss_pct"])
    dd_limit = float(rm["max_total_drawdown_pct"])
    buffer = float(rm["daily_loss_safety_buffer_pct"])
    daily_halt = daily_limit - buffer
    dd_halt = dd_limit - buffer

    latest = db.get_latest_risk_snapshot()
    history = db.get_risk_history(180)
    signals = db.get_signals(limit=400)
    stats = db.get_signal_stats()
    latest_bt = _backtest_view(db.get_latest_backtest())
    by_symbol_bt = [_backtest_view(run) for run in db.get_latest_backtests_by_symbol()]

    daily = float(latest["daily_loss_pct"]) if latest else 0.0
    dd = float(latest["total_drawdown_pct"]) if latest else 0.0
    can_trade = True if latest is None else bool(latest["can_trade"])
    daily_meter = _meter(daily, daily_halt, daily_limit)
    dd_meter = _meter(dd, dd_halt, dd_limit)

    status = "ok"
    if not can_trade or daily_meter["zone"] == "blocked" or dd_meter["zone"] == "blocked":
        status = "blocked"
    elif daily_meter["zone"] == "warning" or dd_meter["zone"] == "warning":
        status = "warning"

    chronological = list(reversed(signals))
    streak = _streak([s["status"] for s in chronological])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": {
            "broker": cfg.get("account", {}).get("broker", "MT5"),
            "symbols": cfg.get("symbols", []),
            "timeframe": cfg.get("timeframes", {}).get("primary", "H1"),
            "confirmation": cfg.get("timeframes", {}).get("confirmation", "H4"),
            "mode": cfg.get("execution", {}).get("mode", "alert_only"),
            "min_confidence": cfg.get("signals", {}).get("min_confidence", 0.6),
            "risk_per_trade_pct": rm.get("risk_per_trade_pct"),
            "max_open_positions": rm.get("max_open_positions"),
        },
        "status": {
            "level": status,
            "can_trade": can_trade,
            "reason": None if latest is None else latest.get("reason"),
            "last_snapshot_age_s": _age_seconds(latest["created_at"]) if latest else None,
            "last_signal_age_s": _age_seconds(signals[0]["created_at"]) if signals else None,
            "last_backtest_age_s": _age_seconds(latest_bt["created_at"]) if latest_bt else None,
        },
        "risk": {
            "latest": latest,
            "daily": daily_meter,
            "drawdown": dd_meter,
            "buffer_pct": buffer,
            "history": [
                {
                    "t": h["created_at"],
                    "equity": h["current_equity"],
                    "daily_loss_pct": h["daily_loss_pct"],
                    "total_drawdown_pct": h["total_drawdown_pct"],
                    "can_trade": h["can_trade"],
                }
                for h in history
            ],
        },
        "signals": {
            "stats": stats,
            "streak": streak,
            "by_symbol": _by_symbol(signals),
            "equity": _live_equity(signals),
            "items": signals[:120],
        },
        "backtest": {
            "latest": latest_bt,
            "by_symbol": by_symbol_bt,
        },
    }
