const API = "";

const el = (id) => document.getElementById(id);

const STATUS_LABEL = {
  on_target: "no alvo",
  late: "atrasado",
  early: "adiantado",
  pending: "pendente",
};

function fmtDelta(item) {
  if (item.delta_min === null || item.delta_min === undefined) return "—";
  const sign = item.delta_min > 0 ? "+" : "";
  return `${sign}${item.delta_min} min`;
}

function eventLabel(ev) {
  if (ev.type === "feed") return ev.subtype === "peito" ? "🤱 Peito" : "🍼 Mamadeira";
  if (ev.type === "bath") return "🛁 Banho";
  if (ev.type === "sleep") return "😴 Sono";
  return ev.type;
}

function timeOf(iso) {
  if (!iso) return "";
  return iso.slice(11, 16);
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "erro na requisição");
  return data;
}

let currentSleepOpen = false;

async function refreshToday() {
  const today = new Date().toISOString().slice(0, 10);
  const state = await api(`/api/state?date=${today}`);
  el("day-badge").textContent = `Dia ${state.day_number}/10`;

  renderAlerts(state.alerts);
  renderComparison(state.comparison);
  renderTimeline(state.events);
  renderWork(state.work_events);

  const open = state.events.find((e) => e.type === "sleep" && !e.end_ts);
  currentSleepOpen = !!open;
  updateSleepButton();
}

function renderAlerts(alerts) {
  const box = el("alerts");
  box.innerHTML = "";
  for (const a of alerts) {
    const div = document.createElement("div");
    div.className = `alert alert-${a.severity}`;
    div.textContent = a.message;
    box.appendChild(div);
  }
}

function renderComparison(comparison) {
  const body = el("comparison-body");
  body.innerHTML = "";
  for (const c of comparison) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${c.label}</td>
      <td>${c.target}</td>
      <td>${c.actual || "—"}</td>
      <td>
        <span class="status-pill status-${c.status}">${STATUS_LABEL[c.status]}</span>
        ${c.delta_min !== null ? `<div class="muted">${fmtDelta(c)}</div>` : ""}
      </td>`;
    body.appendChild(tr);
  }
}

function renderTimeline(events) {
  const ul = el("timeline");
  ul.innerHTML = "";
  if (!events.length) {
    ul.innerHTML = `<li class="t-empty">Nenhum registro ainda hoje.</li>`;
    return;
  }
  for (const ev of events) {
    const li = document.createElement("li");
    const timeStr =
      ev.type === "sleep"
        ? `${timeOf(ev.start_ts)} – ${ev.end_ts ? timeOf(ev.end_ts) : "…"}`
        : timeOf(ev.start_ts);
    li.innerHTML = `
      <span class="t-label">${eventLabel(ev)} <span class="muted">${timeStr}</span></span>
      <button class="del-btn" data-id="${ev.id}" title="Remover">✕</button>`;
    ul.appendChild(li);
  }
  ul.querySelectorAll(".del-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/events/${btn.dataset.id}`, { method: "DELETE" });
      refreshToday();
      refreshWeek();
    });
  });
}

function renderWork(workEvents) {
  const box = el("work-list");
  box.innerHTML = "";
  if (!workEvents.length) {
    box.innerHTML = `<p class="muted">Nenhum compromisso hoje.</p>`;
    return;
  }
  for (const w of workEvents) {
    const div = document.createElement("div");
    div.className = "work-item" + (w.collision ? " collision" : "");
    div.innerHTML = `
      <span>${w.collision ? "⚠️ " : ""}${w.title} — ${timeOf(w.start_ts)}–${timeOf(w.end_ts)}</span>
      <button class="del-btn" data-id="${w.id}">✕</button>`;
    box.appendChild(div);
  }
  box.querySelectorAll(".del-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/work_events/${btn.dataset.id}`, { method: "DELETE" });
      refreshToday();
    });
  });
}

function updateSleepButton() {
  const btn = el("sleep-toggle");
  const label = el("sleep-label");
  const status = el("sleep-status");
  if (currentSleepOpen) {
    btn.classList.add("active");
    label.textContent = "Fim soneca";
    status.textContent = "Soneca em andamento…";
    status.classList.remove("hidden");
  } else {
    btn.classList.remove("active");
    label.textContent = "Início soneca";
    status.classList.add("hidden");
  }
}

async function logQuick(action) {
  try {
    if (action === "feed-peito") await api("/api/events", { method: "POST", body: JSON.stringify({ type: "feed", subtype: "peito" }) });
    else if (action === "feed-mamadeira") await api("/api/events", { method: "POST", body: JSON.stringify({ type: "feed", subtype: "mamadeira" }) });
    else if (action === "bath") await api("/api/events", { method: "POST", body: JSON.stringify({ type: "bath" }) });
    else if (action === "sleep") {
      const type = currentSleepOpen ? "sleep_end" : "sleep_start";
      await api("/api/events", { method: "POST", body: JSON.stringify({ type }) });
    }
    await refreshToday();
    await refreshWeek();
  } catch (e) {
    alert(e.message);
  }
}

async function refreshWeek() {
  const today = new Date().toISOString().slice(0, 10);
  const data = await api(`/api/week?date=${today}`);
  el("streak-number").textContent = data.streak;
  const grid = el("week-grid");
  grid.innerHTML = "";
  const fmt = new Intl.DateTimeFormat("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" });
  for (const d of data.days) {
    const row = document.createElement("div");
    const cls = !d.has_data ? "" : d.met ? "met" : "missed";
    row.className = `week-row ${cls}`;
    const dateObj = new Date(d.date + "T12:00:00");
    const badge = !d.has_data ? "—" : d.met ? "✅" : "⚠️";
    row.innerHTML = `<span>${fmt.format(dateObj)}</span><span class="week-badge">${badge}</span>`;
    grid.appendChild(row);
  }
}

async function loadSettings() {
  const s = await api("/api/settings");
  if (s.transition_start_date) el("start-date").value = s.transition_start_date;
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
      el(`view-${tab.dataset.view}`).classList.remove("hidden");
    });
  });
}

function setupQuickButtons() {
  document.querySelectorAll(".qbtn").forEach((btn) => {
    btn.addEventListener("click", () => logQuick(btn.dataset.action));
  });
}

function setupWorkForm() {
  el("work-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const today = new Date().toISOString().slice(0, 10);
    const title = el("work-title").value.trim() || "Compromisso";
    const start = el("work-start").value;
    const end = el("work-end").value;
    if (!start || !end) return;
    await api("/api/work_events", {
      method: "POST",
      body: JSON.stringify({ date: today, title, start, end }),
    });
    el("work-form").reset();
    refreshToday();
  });
}

function setupSettings() {
  el("save-settings").addEventListener("click", async () => {
    const val = el("start-date").value;
    await api("/api/settings", { method: "POST", body: JSON.stringify({ transition_start_date: val }) });
    el("settings-saved").classList.remove("hidden");
    setTimeout(() => el("settings-saved").classList.add("hidden"), 1500);
    refreshToday();
    refreshWeek();
  });
}

function init() {
  setupTabs();
  setupQuickButtons();
  setupWorkForm();
  setupSettings();
  loadSettings();
  refreshToday();
  refreshWeek();
  setInterval(refreshToday, 60000);
}

document.addEventListener("DOMContentLoaded", init);
