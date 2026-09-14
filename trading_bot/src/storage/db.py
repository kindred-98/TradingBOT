"""
Almacenamiento SQLite.

Persiste señales en vivo, snapshots del Risk Manager y resultados del
backtest walk-forward. main.py y run_backtest.py deben escribir aquí
en vez de limitarse a print(), para que el dashboard y el track record
tengan una fuente única.

Uso:
    db = TradingDB()
    signal_id = db.log_signal(...)
    db.close()
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_DB_PATH = "data/trading_bot.db"

SIGNAL_STATUSES = ("pending", "taken", "skipped", "win", "loss", "expired")
SIGNAL_SIDES = ("BUY", "SELL")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


class TradingDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def close(self):
        self._conn.close()

    def __enter__(self) -> "TradingDB":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _init_schema(self):
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                bar_time TEXT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                signal TEXT NOT NULL CHECK (signal IN ('BUY', 'SELL')),
                confidence REAL NOT NULL,
                entry REAL NOT NULL,
                sl REAL NOT NULL,
                tp REAL NOT NULL,
                atr REAL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'taken', 'skipped', 'win', 'loss', 'expired')),
                closed_at TEXT,
                pnl REAL,
                notes TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_bar
                ON signals (symbol, timeframe, bar_time)
                WHERE bar_time IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_signals_created_at
                ON signals (created_at);

            CREATE INDEX IF NOT EXISTS idx_signals_status
                ON signals (status);

            CREATE TABLE IF NOT EXISTS risk_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                starting_balance_today REAL NOT NULL,
                current_equity REAL NOT NULL,
                initial_balance REAL NOT NULL,
                open_positions INTEGER NOT NULL,
                daily_loss_pct REAL NOT NULL,
                total_drawdown_pct REAL NOT NULL,
                can_trade INTEGER NOT NULL,
                reason TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_risk_created_at
                ON risk_snapshots (created_at);

            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                symbol TEXT,
                n_windows INTEGER NOT NULL,
                train_pct REAL NOT NULL,
                avg_win_rate REAL,
                total_trades INTEGER,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS backtest_windows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
                window INTEGER NOT NULL,
                trades INTEGER NOT NULL,
                wins INTEGER NOT NULL,
                losses INTEGER NOT NULL,
                win_rate REAL NOT NULL,
                no_trade_bars INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_bt_windows_run
                ON backtest_windows (run_id);

            CREATE TABLE IF NOT EXISTS daily_open (
                trade_date TEXT PRIMARY KEY,
                starting_balance REAL NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(backtest_runs)")
        }
        if "symbol" not in cols:
            self._conn.execute("ALTER TABLE backtest_runs ADD COLUMN symbol TEXT")
        self._conn.commit()

    def log_signal(
        self,
        symbol: str,
        timeframe: str,
        signal: str,
        confidence: float,
        entry: float,
        sl: float,
        tp: float,
        atr: Optional[float] = None,
        bar_time: Optional[str] = None,
    ) -> int:
        """
        Registra una señal en vivo. Si ya existe una para el mismo
        symbol/timeframe/bar_time, devuelve el id existente (no duplica).
        """
        if signal not in SIGNAL_SIDES:
            raise ValueError(f"signal debe ser BUY o SELL, recibido: {signal}")

        if bar_time is not None:
            existing = self._conn.execute(
                """
                SELECT id FROM signals
                WHERE symbol = ? AND timeframe = ? AND bar_time = ?
                """,
                (symbol, timeframe, bar_time),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])

        cur = self._conn.execute(
            """
            INSERT INTO signals (
                created_at, bar_time, symbol, timeframe, signal,
                confidence, entry, sl, tp, atr
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(), bar_time, symbol, timeframe, signal,
                float(confidence), float(entry), float(sl), float(tp),
                None if atr is None else float(atr),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update_signal_result(
        self,
        signal_id: int,
        status: str,
        pnl: Optional[float] = None,
        notes: Optional[str] = None,
    ):
        """Actualiza el resultado de una señal (taken/skipped/win/loss/expired)."""
        if status not in SIGNAL_STATUSES:
            raise ValueError(f"status inválido: {status}. Válidos: {SIGNAL_STATUSES}")
        if status == "pending":
            raise ValueError("No se puede volver una señal a pending")

        cur = self._conn.execute(
            """
            UPDATE signals
            SET status = ?,
                pnl = ?,
                notes = COALESCE(?, notes),
                closed_at = CASE
                    WHEN ? IN ('win', 'loss', 'skipped', 'expired') THEN ?
                    ELSE closed_at
                END
            WHERE id = ?
            """,
            (status, pnl, notes, status, _utc_now(), signal_id),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise KeyError(f"Señal id={signal_id} no existe")

    def get_signal(self, signal_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM signals WHERE id = ?", (signal_id,)
        ).fetchone()
        return _row_to_dict(row)

    def get_signals(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        clauses = []
        params: list = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM signals {where} ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_signal_stats(self) -> dict:
        """Win rate del track record en vivo (solo win/loss cerrados)."""
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'taken' THEN 1 ELSE 0 END) AS taken,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                SUM(CASE WHEN status = 'win' THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN status = 'loss' THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) AS expired,
                COALESCE(SUM(pnl), 0) AS total_pnl
            FROM signals
            """
        ).fetchone()
        data = dict(row)
        closed = (data["wins"] or 0) + (data["losses"] or 0)
        data["closed"] = closed
        data["win_rate"] = round((data["wins"] or 0) / closed, 3) if closed else None
        return data

    def log_risk_snapshot(
        self,
        starting_balance_today: float,
        current_equity: float,
        initial_balance: float,
        open_positions: int,
        daily_loss_pct: float,
        total_drawdown_pct: float,
        can_trade: bool,
        reason: str,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO risk_snapshots (
                created_at, starting_balance_today, current_equity,
                initial_balance, open_positions, daily_loss_pct,
                total_drawdown_pct, can_trade, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(),
                float(starting_balance_today),
                float(current_equity),
                float(initial_balance),
                int(open_positions),
                float(daily_loss_pct),
                float(total_drawdown_pct),
                1 if can_trade else 0,
                reason,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_latest_risk_snapshot(self) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM risk_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        data = _row_to_dict(row)
        if data is not None:
            data["can_trade"] = bool(data["can_trade"])
        return data

    def log_backtest_run(
        self,
        n_windows: int,
        train_pct: float,
        windows: list[dict],
        symbol: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Guarda una corrida walk-forward. `windows` debe coincidir con las
        filas que hoy imprime run_backtest.py:
        window, trades, wins, losses, win_rate, no_trade_bars.
        """
        if not windows:
            raise ValueError("windows no puede estar vacío")

        total_trades = sum(int(w["trades"]) for w in windows)
        avg_win_rate = sum(float(w["win_rate"]) for w in windows) / len(windows)

        cur = self._conn.execute(
            """
            INSERT INTO backtest_runs (
                created_at, symbol, n_windows, train_pct,
                avg_win_rate, total_trades, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now(), symbol, int(n_windows), float(train_pct),
                round(avg_win_rate, 4), total_trades, notes,
            ),
        )
        run_id = int(cur.lastrowid)

        self._conn.executemany(
            """
            INSERT INTO backtest_windows (
                run_id, window, trades, wins, losses, win_rate, no_trade_bars
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    int(w["window"]),
                    int(w["trades"]),
                    int(w["wins"]),
                    int(w["losses"]),
                    float(w["win_rate"]),
                    int(w["no_trade_bars"]),
                )
                for w in windows
            ],
        )
        self._conn.commit()
        return run_id

    def get_backtest_run(self, run_id: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM backtest_runs WHERE id = ?", (run_id,)
        ).fetchone()
        data = _row_to_dict(row)
        if data is None:
            return None
        windows = self._conn.execute(
            "SELECT * FROM backtest_windows WHERE run_id = ? ORDER BY window ASC",
            (run_id,),
        ).fetchall()
        data["windows"] = [dict(w) for w in windows]
        return data

    def get_latest_backtest(self) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id FROM backtest_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self.get_backtest_run(int(row["id"]))

    def get_recent_backtests(self, limit: int = 12) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id FROM backtest_runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self.get_backtest_run(int(r["id"])) for r in rows]

    def get_latest_backtests_by_symbol(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT MAX(id) AS id
            FROM backtest_runs
            GROUP BY COALESCE(symbol, '')
            ORDER BY id DESC
            """
        ).fetchall()
        return [self.get_backtest_run(int(r["id"])) for r in rows]

    def upsert_daily_open(self, trade_date: str, starting_balance: float):
        self._conn.execute(
            """
            INSERT INTO daily_open (trade_date, starting_balance, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(trade_date) DO UPDATE SET
                starting_balance = excluded.starting_balance
            """,
            (trade_date, float(starting_balance), _utc_now()),
        )
        self._conn.commit()

    def get_daily_open(self, trade_date: str) -> Optional[float]:
        row = self._conn.execute(
            "SELECT starting_balance FROM daily_open WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
        return None if row is None else float(row["starting_balance"])

    def get_risk_history(self, limit: int = 250) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM risk_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = [dict(r) for r in rows]
        out.reverse()
        for item in out:
            item["can_trade"] = bool(item["can_trade"])
        return out
