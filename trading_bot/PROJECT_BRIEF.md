# Project Brief — Trading Bot (Day Trading / Swing)

## Objetivo
Bot de señales de trading para cuentas de fondeo (FTMO y FundedPips), operando
sobre MT5. Detecta señales de entrada/salida y avisa por Telegram; ejecución
manual por ahora, con opción de semi-auto/auto más adelante SOLO tras validar
track record real.

## Decisiones ya tomadas (no las reabras salvo que encuentres un problema real)
- Timeframe: H1 como señal principal, H4 como confirmación de tendencia.
  Descartado scalping (M1-M5) por ratio señal/ruido malo y costos de transacción.
- Lenguaje: Python para todo el pipeline (datos, features, modelo, riesgo,
  backtest). MQL5 solo si más adelante se necesita ejecución nativa de baja
  latencia dentro de MT5 — no es necesario para day trading/swing.
- Broker/plataforma: MT5 (tanto FTMO como FundedPips operan bots sobre MT5).
- Señales base: EMA rápida/lenta, SMA de tendencia, volumen relativo, ATR,
  RSI, MACD, patrones de vela (engulfing). Ya implementadas en
  `src/features/indicators.py`.
- Modelo: XGBoost como clasificador de señal (BUY/SELL/no operar), entrenado
  sobre esos features con etiquetado por movimiento futuro ajustado a ATR.
  Ya implementado en `src/signals/model.py`.
- Risk Manager (`src/risk/risk_manager.py`) es la pieza crítica: límites de
  pérdida diaria y drawdown total con buffer de seguridad antes del límite
  real de la prop firm, sizing de posición basado en % de riesgo fijo.
  Tratar como código sensible — cualquier cambio se revisa con cuidado.
- Modo de ejecución: `alert_only` (Telegram) hasta tener track record
  validado. `auto` está deliberadamente sin implementar.

## Estado actual del código
Esqueleto ya creado y funcional (estructura de archivos), pendiente de
completar lo siguiente:

1. **Dashboard** (nuevo, módulo separado `src/dashboard/`):
   - Historial de señales + resultado
   - Win rate y curva de equity del backtest walk-forward
   - Estado del Risk Manager en tiempo real
   - Resultados de la última corrida de backtest
2. **Almacenamiento** (nuevo, `src/storage/db.py`): SQLite para que
   main.py y run_backtest.py registren cada señal/resultado en vez de
   solo hacer print().
3. **TODOs pendientes en `main.py`**:
   - Leer balance de apertura del día real (no el balance actual)
   - Leer posiciones abiertas reales vía `mt5.positions_get()`

## Cómo trabajar en esto
Ir fase por fase (storage → integración en main/backtest → dashboard →
TODOs de main.py), mostrando el resultado de cada fase antes de seguir a
la siguiente. No generar todo de golpe sin revisión intermedia — este
sistema va a operar sobre una cuenta fondeada real.

## Qué NO hacer todavía
- No implementar `mt5.order_send()` ni el modo de ejecución `auto`.
- No bajar a timeframes de scalping (M1-M5).
- No modificar los límites de `risk_management` en `config.yaml` sin
  verificarlos contra las reglas actuales y reales de la cuenta FTMO/FundedPips.
