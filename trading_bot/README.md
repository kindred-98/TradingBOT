# Trading Bot — Day Trading / Swing (H1-H4)

Bot de señales para cuentas de fondeo (FTMO / FundedPips) sobre MT5.
Arranca en modo **alert_only**: te avisa por Telegram, tú ejecutas manual.
No actives ejecución automática hasta validar el modelo con track record real.

## Estructura

```
trading_bot/
├── config/config.yaml        # símbolos, timeframes, límites de riesgo
├── src/
│   ├── data/mt5_connector.py     # conexión a MT5, datos históricos y en vivo
│   ├── features/indicators.py    # EMA, SMA, volumen, ATR, RSI, patrones de vela
│   ├── signals/model.py          # etiquetado + entrenamiento XGBoost + predicción
│   ├── risk/risk_manager.py      # límites de drawdown de la prop firm (NO TOCAR sin entender bien)
│   ├── alerts/telegram_alert.py  # alertas de señal
│   └── backtest/run_backtest.py  # walk-forward validation
├── main.py                   # loop principal en vivo
├── requirements.txt
└── .env.example               # copia a .env con tus credenciales reales
```

## Setup

1. Instala MT5 en Windows (o Wine en Linux) y loguéate en tu cuenta de fondeo.
2. `pip install -r requirements.txt`
3. Copia `.env.example` a `.env` y completa tus credenciales de MT5 y Telegram.
4. Ajusta `config/config.yaml`:
   - `risk_management`: pon los límites REALES de tu cuenta (FTMO y FundedPips
     pueden diferir — verifica en el panel de tu prop firm).
   - `symbols`: los pares que operas.

## Orden de trabajo recomendado (no te saltes pasos)

1. **Backtest primero**: corre `src/backtest/run_backtest.py` sobre datos
   históricos de MT5. Si el win rate varía mucho entre ventanas o es apenas
   >50%, el modelo no tiene edge todavía — no sigas al paso 2.
2. **Entrena el modelo final** con `src/signals/model.py::train()` sobre
   todo el histórico, una vez el backtest walk-forward te convenza.
3. **Corre `main.py` en modo `alert_only`** durante varias semanas. Registra
   cada señal y si la hubieras tomado o no, y el resultado real.
4. **Solo si el track record de la fase 3 es positivo**, evalúa activar
   `semi_auto` o `auto` — y aun así, con el `risk_per_trade_pct` bajo.

## Sobre el Risk Manager

Es la única pieza que asumí "terminada" en vez de un esqueleto — está escrita
para ser simple y auditable, porque es lo que te protege de romper las reglas
de drawdown de FTMO/FundedPips aunque el modelo falle. Revísala igual línea
por línea antes de confiar en ella con dinero real.

## Pendiente de implementar (marcado con TODO en el código)

- `main.py`: leer el balance de apertura del día real (no el balance actual)
  y las posiciones abiertas reales vía `mt5.positions_get()`.
- `main.py`: `mt5.order_send()` para el modo `auto` (deshabilitado a propósito).
- Panel/dashboard para revisar el track record de las señales (fase 3).
