"""
Conector a MetaTrader 5.
Requiere que el terminal MT5 esté instalado y con sesión iniciada en la
cuenta de la prop firm (FTMO / FundedPips corren sobre MT5).

Instalación: pip install MetaTrader5 pandas
NOTA: el paquete MetaTrader5 solo funciona en Windows (o Linux vía Wine),
porque envuelve la API nativa del terminal.
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from typing import Optional


TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class MT5Connector:
    def __init__(self, login: int, password: str, server: str):
        self.login = login
        self.password = password
        self.server = server
        self._connected = False

    def connect(self) -> bool:
        if not mt5.initialize():
            raise RuntimeError(f"No se pudo inicializar MT5: {mt5.last_error()}")

        authorized = mt5.login(
            login=self.login, password=self.password, server=self.server
        )
        if not authorized:
            raise RuntimeError(f"Login MT5 falló: {mt5.last_error()}")

        self._connected = True
        return True

    def disconnect(self):
        mt5.shutdown()
        self._connected = False

    def get_historical_data(
        self, symbol: str, timeframe: str, n_bars: int = 1000
    ) -> pd.DataFrame:
        """Trae las últimas n_bars velas históricas para entrenar/backtestear."""
        if not self._connected:
            raise RuntimeError("No conectado a MT5. Llama a connect() primero.")

        tf = TIMEFRAME_MAP[timeframe]
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is None:
            raise RuntimeError(f"No se pudieron obtener datos: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.rename(columns={"tick_volume": "volume"})
        return df[["time", "open", "high", "low", "close", "volume"]]

    def get_live_price(self, symbol: str) -> Optional[dict]:
        """Precio/tick actual — úsalo para la lógica de ejecución en vivo."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return {
            "time": datetime.fromtimestamp(tick.time),
            "bid": tick.bid,
            "ask": tick.ask,
            "spread": round(tick.ask - tick.bid, 5),
        }

    def get_account_info(self) -> dict:
        """Balance, equity, drawdown actual — el Risk Manager depende de esto."""
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"No se pudo leer la cuenta: {mt5.last_error()}")
        return {
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "profit": info.profit,
        }

    def get_open_positions(self) -> list[dict]:
        """Posiciones abiertas reales vía mt5.positions_get()."""
        if not self._connected:
            raise RuntimeError("No conectado a MT5. Llama a connect() primero.")
        positions = mt5.positions_get()
        if positions is None:
            err = mt5.last_error()
            if err and err[0] != mt5.RES_S_OK:
                raise RuntimeError(f"No se pudieron leer posiciones: {err}")
            return []
        return [
            {
                "ticket": int(p.ticket),
                "symbol": p.symbol,
                "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "profit": float(p.profit),
            }
            for p in positions
        ]

    def get_day_opening_balance(self) -> float:
        """
        Balance al inicio del día local: balance actual menos el PnL
        realizado hoy (cierres, swap, comisión). Así no se usa el balance
        corriente, que ya incluye operaciones cerradas en la sesión.
        """
        if not self._connected:
            raise RuntimeError("No conectado a MT5. Llama a connect() primero.")
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"No se pudo leer la cuenta: {mt5.last_error()}")

        now = datetime.now()
        day_start = datetime(now.year, now.month, now.day)
        deals = mt5.history_deals_get(day_start, now)
        realized = 0.0
        if deals:
            for deal in deals:
                realized += float(deal.profit) + float(deal.swap) + float(deal.commission)
        return round(float(info.balance) - realized, 2)
