"""
Dashboard local del bot: riesgo, señales y último walk-forward.

Desde trading_bot/: python src/dashboard/app.py
Luego abre http://127.0.0.1:8050
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.dashboard.metrics import build_overview
from src.storage.db import TradingDB

DASH_DIR = Path(__file__).resolve().parent
CONFIG_PATH = _ROOT / "config" / "config.yaml"
DB_PATH = _ROOT / "data" / "trading_bot.db"
INDEX_PATH = DASH_DIR / "templates" / "index.html"

app = FastAPI(title="TradingBOT Desk", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(DASH_DIR / "static")), name="static")


def _load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_PATH.read_text(encoding="utf-8")


@app.get("/api/overview")
def overview():
    cfg = _load_config()
    db = TradingDB(str(DB_PATH))
    try:
        return build_overview(db, cfg)
    finally:
        db.close()


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8050, log_level="info")


if __name__ == "__main__":
    main()
