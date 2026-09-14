"""
Envía alertas de señal a Telegram. Empiezas en modo "alert_only":
el bot te avisa, tú decides y ejecutas manualmente.

Setup:
1. Habla con @BotFather en Telegram, crea un bot, copia el token.
2. Escríbele algo a tu bot, luego visita:
   https://api.telegram.org/bot<TOKEN>/getUpdates
   para obtener tu chat_id.
3. Guarda ambos en tu archivo .env (ver .env.example).

Instalación: pip install python-telegram-bot python-dotenv
"""

import asyncio
from telegram import Bot


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def send_signal_alert(
        self, symbol: str, signal: str, confidence: float,
        entry: float, sl: float, tp: float, timeframe: str
    ):
        emoji = "🟢" if signal == "BUY" else "🔴"
        text = (
            f"{emoji} *{signal} {symbol}* ({timeframe})\n\n"
            f"Confianza del modelo: {confidence:.0%}\n"
            f"Entrada sugerida: {entry}\n"
            f"Stop Loss: {sl}\n"
            f"Take Profit: {tp}\n\n"
            f"_Revisa el contexto antes de ejecutar. Esto es una señal, no una orden._"
        )
        await self.bot.send_message(
            chat_id=self.chat_id, text=text, parse_mode="Markdown"
        )

    async def send_risk_block(self, reason: str):
        await self.bot.send_message(
            chat_id=self.chat_id, text=f"⚠️ {reason}"
        )


def send_alert_sync(alerter: TelegramAlerter, *args, **kwargs):
    """Wrapper síncrono para llamar desde main.py sin lidiar con async directamente."""
    asyncio.run(alerter.send_signal_alert(*args, **kwargs))
