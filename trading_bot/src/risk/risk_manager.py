"""
Risk Manager — LA pieza más importante del sistema.

Este módulo NO opina sobre si la señal es buena. Su único trabajo es
proteger la cuenta de fondeo: si el modelo se equivoca, el que evita que
revientes la cuenta es este código, no el modelo.

Diseñado deliberadamente simple y sin dependencias del modelo de ML,
para que puedas auditarlo línea por línea con confianza total.
"""

from dataclasses import dataclass
from datetime import date


@dataclass
class RiskState:
    starting_balance_today: float
    current_equity: float
    initial_balance: float  # balance con el que arrancó la cuenta fondeada
    open_positions: int
    trade_date: date


class RiskManager:
    def __init__(self, cfg: dict):
        rm = cfg["risk_management"]
        self.max_daily_loss_pct = rm["max_daily_loss_pct"]
        self.max_total_drawdown_pct = rm["max_total_drawdown_pct"]
        self.risk_per_trade_pct = rm["risk_per_trade_pct"]
        self.max_open_positions = rm["max_open_positions"]
        self.safety_buffer_pct = rm["daily_loss_safety_buffer_pct"]

    def daily_loss_pct(self, state: RiskState) -> float:
        loss = state.starting_balance_today - state.current_equity
        return max(0.0, (loss / state.starting_balance_today) * 100)

    def total_drawdown_pct(self, state: RiskState) -> float:
        loss = state.initial_balance - state.current_equity
        return max(0.0, (loss / state.initial_balance) * 100)

    def can_open_trade(self, state: RiskState) -> tuple[bool, str]:
        """
        Devuelve (permitido, motivo). Se llama ANTES de cada operación,
        automática o manual.
        """
        daily_loss = self.daily_loss_pct(state)
        total_dd = self.total_drawdown_pct(state)

        # Buffer de seguridad: nos detenemos ANTES del límite real de la prop firm
        daily_limit_with_buffer = self.max_daily_loss_pct - self.safety_buffer_pct

        if daily_loss >= daily_limit_with_buffer:
            return False, (
                f"BLOQUEADO: pérdida diaria {daily_loss:.2f}% cerca del límite "
                f"({self.max_daily_loss_pct}%). Se detiene por hoy."
            )

        if total_dd >= self.max_total_drawdown_pct - self.safety_buffer_pct:
            return False, (
                f"BLOQUEADO: drawdown total {total_dd:.2f}% cerca del límite "
                f"({self.max_total_drawdown_pct}%). Revisa la cuenta."
            )

        if state.open_positions >= self.max_open_positions:
            return False, "BLOQUEADO: máximo de posiciones abiertas alcanzado."

        return True, "OK"

    def position_size(
        self, state: RiskState, entry_price: float, stop_loss_price: float,
        pip_value_per_lot: float
    ) -> float:
        """
        Calcula el tamaño de posición para arriesgar exactamente
        risk_per_trade_pct del balance, según la distancia al SL.
        Nunca dejes que el modelo o tú decidan el tamaño "a ojo".
        """
        risk_amount = state.current_equity * (self.risk_per_trade_pct / 100)
        sl_distance = abs(entry_price - stop_loss_price)

        if sl_distance == 0:
            return 0.0

        lots = risk_amount / (sl_distance * pip_value_per_lot)
        return round(lots, 2)
