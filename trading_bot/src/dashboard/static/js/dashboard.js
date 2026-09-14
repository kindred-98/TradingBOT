const charts = {};
let lastSignals = [];

const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: "#101623",
      borderColor: "#1c2433",
      borderWidth: 1,
      titleColor: "#8b95a8",
      bodyColor: "#e8eef7",
      padding: 10,
    },
  },
  scales: {
    x: {
      ticks: { color: "#8b95a8", maxRotation: 0, font: { family: "IBM Plex Mono", size: 10 } },
      grid: { color: "rgba(28,36,51,0.7)" },
      border: { color: "#1c2433" },
    },
    y: {
      ticks: { color: "#8b95a8", font: { family: "IBM Plex Mono", size: 10 } },
      grid: { color: "rgba(28,36,51,0.7)" },
      border: { color: "#1c2433" },
    },
  },
};

function upsertChart(id, data, extra = {}) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  if (charts[id]) {
    charts[id].data = data;
    charts[id].update("none");
    charts[id].resize();
    return;
  }
  charts[id] = new Chart(canvas, {
    ...extra,
    options: { ...chartDefaults, ...(extra.options || {}) },
    data,
  });
  charts[id].resize();
}

function pct(v, fromRatio = false) {
  if (v === null || v === undefined) return "—";
  const n = fromRatio ? v * 100 : v;
  return `${n.toFixed(1)}%`;
}

function money(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function age(seconds) {
  if (seconds === null || seconds === undefined) return "sin datos";
  if (seconds < 60) return `hace ${seconds}s`;
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)}h`;
  return `hace ${Math.floor(seconds / 86400)}d`;
}

function shortTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-ES", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function setChip(level, canTrade) {
  const chip = document.getElementById("status-chip");
  chip.className = `status-chip ${level}`;
  chip.textContent = level === "blocked" || !canTrade ? "bloqueado" : level === "warning" ? "precaución" : "operativo";
}

function renderBanner(data) {
  const el = document.getElementById("status-banner");
  const level = data.status.level;
  if (level === "ok") {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.className = `banner ${level}`;
  el.textContent = data.status.reason || (level === "blocked"
    ? "Risk Manager ha detenido nuevas entradas."
    : "Te estás acercando al buffer de seguridad.");
}

function kpi(label, value, sub, zone = "") {
  return `<div class="kpi ${zone}"><span>${label}</span><strong>${value}</strong><em>${sub || ""}</em></div>`;
}

function renderKpis(data) {
  const r = data.risk;
  const latest = r.latest;
  const stats = data.signals.stats;
  const wr = stats.win_rate == null ? "—" : pct(stats.win_rate, true);
  const streak = data.signals.streak.current;
  const streakTxt = streak.side
    ? `${streak.count} ${streak.side === "win" ? "wins" : "losses"}`
    : "sin racha";
  document.getElementById("kpis").innerHTML = [
    kpi("Estado", latest ? (data.status.can_trade ? "OK" : "STOP") : "—", age(data.status.last_snapshot_age_s), latest ? data.status.level : ""),
    kpi("Equity", latest ? money(latest.current_equity) : "—", latest ? `open día ${money(latest.starting_balance_today)} · ${latest.open_positions} pos` : "espera snapshot"),
    kpi("Pérdida diaria", latest ? `${r.daily.value.toFixed(2)}%` : "—", `halt ${r.daily.halt_at.toFixed(1)}% · límite ${r.daily.hard_limit.toFixed(1)}%`, latest ? r.daily.zone : ""),
    kpi("Drawdown total", latest ? `${r.drawdown.value.toFixed(2)}%` : "—", `halt ${r.drawdown.halt_at.toFixed(1)}% · límite ${r.drawdown.hard_limit.toFixed(1)}%`, latest ? r.drawdown.zone : ""),
    kpi("Win rate vivo", wr, `${stats.wins || 0}W / ${stats.losses || 0}L · ${streakTxt}`),
    kpi("PnL cerrado", money(stats.total_pnl), `${stats.pending || 0} pending · ${stats.total || 0} señales`),
  ].join("");
}

function meterHtml(title, meter, caption) {
  const width = Math.min(100, meter.utilization * 100);
  const halt = meter.hard_limit > 0 ? (meter.halt_at / meter.hard_limit) * 100 : 0;
  return `
    <div class="meter">
      <div class="meter-top"><span>${title}</span><b>${meter.value.toFixed(2)}%</b></div>
      <div class="track">
        <div class="fill ${meter.zone}" style="width:${width}%"></div>
        <div class="halt" style="left:${halt}%"></div>
      </div>
      <div class="meter-legend">
        <span>0%</span>
        <span>halt ${meter.halt_at.toFixed(1)}%</span>
        <span>límite ${meter.hard_limit.toFixed(1)}%</span>
      </div>
      <p class="empty">${caption}</p>
    </div>`;
}

function renderRisk(data) {
  const r = data.risk;
  document.getElementById("risk-meters").innerHTML =
    meterHtml("Pérdida diaria", r.daily, `Headroom hasta halt: ${r.daily.headroom.toFixed(2)} puntos porcentuales. Buffer interno ${r.buffer_pct}%.`)
    + meterHtml("Drawdown total", r.drawdown, `Headroom hasta halt: ${r.drawdown.headroom.toFixed(2)} puntos. Si llega aquí, revisa la cuenta antes de seguir.`);
}

function labelsFrom(points, key = "t") {
  return points.map((p, i) => shortTime(p[key]) || String(i));
}

function renderCharts(data) {
  const eqHist = data.risk.history;
  const eqEmpty = document.getElementById("equity-empty");
  const eqCanvas = document.getElementById("chart-equity").parentElement;
  if (!eqHist.length) {
    eqEmpty.hidden = false;
    eqCanvas.hidden = true;
  } else {
    eqEmpty.hidden = true;
    eqCanvas.hidden = false;
    upsertChart("chart-equity", {
      labels: labelsFrom(eqHist),
      datasets: [{
        data: eqHist.map((p) => p.equity),
        borderColor: "#6aa8ff",
        backgroundColor: "rgba(106,168,255,0.12)",
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      }],
    }, { type: "line" });
  }

  const live = data.signals.equity;
  const liveEmpty = document.getElementById("live-empty");
  const liveCanvas = document.getElementById("chart-live").parentElement;
  if (!live.length) {
    liveEmpty.hidden = false;
    liveCanvas.hidden = true;
  } else {
    liveEmpty.hidden = true;
    liveCanvas.hidden = false;
    upsertChart("chart-live", {
      labels: labelsFrom(live),
      datasets: [{
        data: live.map((p) => p.v),
        borderColor: live[live.length - 1].v >= 0 ? "#3ddc97" : "#ff5c7a",
        backgroundColor: live[live.length - 1].v >= 0 ? "rgba(61,220,151,0.12)" : "rgba(255,92,122,0.12)",
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
      }],
    }, { type: "line" });
  }

  const bt = data.backtest.latest;
  const btEmpty = document.getElementById("bt-empty");
  const btEq = document.getElementById("chart-bt-equity").parentElement;
  const btWin = document.getElementById("chart-bt-windows").parentElement;
  const cons = document.getElementById("bt-consistency");
  if (!bt) {
    btEmpty.hidden = false;
    btEq.hidden = true;
    btWin.hidden = true;
    cons.textContent = "sin datos";
    return;
  }
  btEmpty.hidden = true;
  btEq.hidden = false;
  btWin.hidden = false;
  const labelMap = { ok: "estable", watch: "revisar", unstable: "inestable", empty: "vacío" };
  cons.textContent = labelMap[bt.consistency] || bt.consistency;
  cons.className = `pill ${bt.consistency === "ok" ? "" : "pill-ghost"}`;
  document.getElementById("bt-subtitle").textContent =
    `${bt.symbol || "multi"} · wr medio ${(bt.avg_win_rate * 100).toFixed(1)}% · spread ${(bt.spread * 100).toFixed(1)} pts · ${age(data.status.last_backtest_age_s)}`;

  upsertChart("chart-bt-equity", {
    labels: bt.equity_r.map((p) => p.t < 0 ? "start" : `W${p.t}`),
    datasets: [{
      data: bt.equity_r.map((p) => p.v),
      borderColor: "#3ddc97",
      backgroundColor: "rgba(61,220,151,0.12)",
      fill: true,
      tension: 0.2,
      pointRadius: 3,
      borderWidth: 2,
    }],
  }, { type: "line" });

  upsertChart("chart-bt-windows", {
    labels: (bt.windows || []).map((w) => `W${w.window}`),
    datasets: [{
      data: (bt.windows || []).map((w) => w.win_rate * 100),
      backgroundColor: (bt.windows || []).map((w) => w.win_rate >= 0.55 ? "rgba(61,220,151,0.75)" : w.win_rate >= 0.45 ? "rgba(255,176,32,0.8)" : "rgba(255,92,122,0.8)"),
      borderRadius: 6,
    }],
  }, { type: "bar", options: { ...chartDefaults, scales: { ...chartDefaults.scales, y: { ...chartDefaults.scales.y, suggestedMin: 0, suggestedMax: 100 } } } });
}

function renderSignals(items) {
  const symbol = document.getElementById("filter-symbol").value;
  const status = document.getElementById("filter-status").value;
  const rows = items.filter((s) => (!symbol || s.symbol === symbol) && (!status || s.status === status));
  const body = document.getElementById("signals-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="9" class="muted">No hay señales con ese filtro.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((s) => {
    const conf = Math.round((s.confidence || 0) * 100);
    return `<tr>
      <td>${shortTime(s.created_at)}</td>
      <td>${s.symbol}</td>
      <td class="side ${s.signal}">${s.signal}</td>
      <td><span class="conf"><i style="width:${conf}%"></i></span>${conf}%</td>
      <td>${s.entry}</td>
      <td>${s.sl}</td>
      <td>${s.tp}</td>
      <td><span class="badge ${s.status}">${s.status}</span></td>
      <td>${s.pnl == null ? "—" : money(s.pnl)}</td>
    </tr>`;
  }).join("");
}

function syncSymbolFilter(items, metaSymbols) {
  const sel = document.getElementById("filter-symbol");
  const current = sel.value;
  const symbols = [...new Set([...(metaSymbols || []), ...items.map((s) => s.symbol)])].filter(Boolean).sort();
  sel.innerHTML = `<option value="">Todos los pares</option>` + symbols.map((s) => `<option value="${s}">${s}</option>`).join("");
  if (symbols.includes(current)) sel.value = current;
}

function renderWindows(data) {
  const runs = data.backtest.by_symbol || [];
  const body = document.getElementById("windows-body");
  const rows = [];
  runs.forEach((run) => {
    (run.windows || []).forEach((w) => {
      rows.push(`<tr>
        <td>${run.symbol || "—"}</td>
        <td>W${w.window}</td>
        <td>${w.trades}</td>
        <td>${w.wins}</td>
        <td>${w.losses}</td>
        <td>${(w.win_rate * 100).toFixed(1)}%</td>
        <td>${w.no_trade_bars}</td>
      </tr>`);
    });
  });
  body.innerHTML = rows.length ? rows.join("") : `<tr><td colspan="7" class="muted">Sin ventanas de backtest.</td></tr>`;
}

function render(data) {
  const m = data.meta;
  document.getElementById("meta-line").textContent =
    `${m.broker} · ${m.timeframe}/${m.confirmation} · ${m.symbols.join(" · ")} · riesgo ${m.risk_per_trade_pct}% / trade`;
  document.getElementById("mode-pill").textContent = m.mode;
  setChip(data.status.level, data.status.can_trade);
  renderBanner(data);
  renderKpis(data);
  renderRisk(data);
  renderCharts(data);
  lastSignals = data.signals.items || [];
  syncSymbolFilter(lastSignals, m.symbols);
  renderSignals(lastSignals);
  renderWindows(data);
}

async function refresh() {
  if (document.hidden) return;
  try {
    const res = await fetch("/api/overview");
    if (!res.ok) throw new Error(res.statusText);
    render(await res.json());
  } catch (err) {
    document.getElementById("status-chip").textContent = "sin conexión";
    document.getElementById("status-chip").className = "status-chip blocked";
  }
}

document.getElementById("filter-symbol").addEventListener("change", () => renderSignals(lastSignals));
document.getElementById("filter-status").addEventListener("change", () => renderSignals(lastSignals));

setInterval(() => {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("es-ES");
}, 1000);

refresh();
setInterval(refresh, 8000);
