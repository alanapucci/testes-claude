const API = "";

const el = (id) => document.getElementById(id);
const todayStr = () => new Date().toISOString().slice(0, 10);

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

// ---------------------------------------------------------------------
// Estado de soneca em andamento, por pessoa
// ---------------------------------------------------------------------
const sleepOpen = { bebe: false, rapha: false };

function updateSleepButton(person) {
  const btn = el(`sleep-toggle-${person}`);
  const label = el(`sleep-label-${person}`);
  const status = el(`sleep-status-${person}`);
  if (sleepOpen[person]) {
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

// ---------------------------------------------------------------------
// Bebê / Rapha: registro, comparação, timeline
// ---------------------------------------------------------------------

async function refreshPerson(person) {
  const state = await api(`/api/state?date=${todayStr()}&person=${person}`);

  if (person === "bebe") {
    el("day-badge").textContent = `Dia ${state.day_number}/10`;
    renderAlerts("bebe-alerts", state.alerts);
    renderWork(state.work_events);
  } else {
    renderAlerts("rapha-alerts", state.alerts);
  }

  renderComparison(`comparison-body-${person}`, state.comparison);
  renderTimeline(`timeline-${person}`, state.events);

  const open = state.events.find((e) => e.type === "sleep" && !e.end_ts);
  sleepOpen[person] = !!open;
  updateSleepButton(person);

  return state;
}

function renderAlerts(containerId, alerts) {
  const box = el(containerId);
  box.innerHTML = "";
  for (const a of alerts) {
    const div = document.createElement("div");
    div.className = `alert alert-${a.severity}`;
    div.textContent = a.message;
    box.appendChild(div);
  }
}

function renderComparison(bodyId, comparison) {
  const body = el(bodyId);
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

function renderTimeline(listId, events) {
  const ul = el(listId);
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
      refreshAll();
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
      refreshPerson("bebe");
    });
  });
}

async function logQuick(person, action) {
  try {
    if (action === "feed-peito") await api("/api/events", { method: "POST", body: JSON.stringify({ type: "feed", subtype: "peito", person }) });
    else if (action === "feed-mamadeira") await api("/api/events", { method: "POST", body: JSON.stringify({ type: "feed", subtype: "mamadeira", person }) });
    else if (action === "bath") await api("/api/events", { method: "POST", body: JSON.stringify({ type: "bath", person }) });
    else if (action === "sleep") {
      const type = sleepOpen[person] ? "sleep_end" : "sleep_start";
      await api("/api/events", { method: "POST", body: JSON.stringify({ type, person }) });
    }
    await refreshAll();
  } catch (e) {
    alert(e.message);
  }
}

// ---------------------------------------------------------------------
// Casa
// ---------------------------------------------------------------------

async function refreshHouse() {
  const data = await api(`/api/house?date=${todayStr()}`);
  renderHouseInto("house-fill", "house-list", "house-summary", data);
  return data;
}

function renderHouseInto(fillId, listId, summaryId, data) {
  el(fillId).style.width = `${data.percent}%`;
  if (summaryId) {
    el(summaryId).textContent = `${data.done_minutes} de ${data.total_minutes} min feitos (${data.percent}%)`;
  }
  const ul = el(listId);
  if (!ul) return;
  ul.innerHTML = "";
  for (const t of data.tasks) {
    const li = document.createElement("li");
    li.className = "house-item" + (t.done ? " done" : "");
    li.dataset.key = t.key;
    li.innerHTML = `
      <span class="house-check">✓</span>
      <span class="house-label">${t.label}</span>
      <span class="house-minutes">${t.minutes}min</span>`;
    li.addEventListener("click", () => toggleHouseTask(t.key, !t.done));
    ul.appendChild(li);
  }
}

async function toggleHouseTask(key, done) {
  await api("/api/house/toggle", {
    method: "POST",
    body: JSON.stringify({ date: todayStr(), key, done }),
  });
  await refreshAll();
}

// ---------------------------------------------------------------------
// Flags: crianças na cama / rotina pessoal da mãe
// ---------------------------------------------------------------------

function renderFlag(btnId, infoId, flag, isBedtime) {
  const btn = el(btnId);
  const info = el(infoId);
  btn.classList.remove("done", "late");
  if (flag.done) {
    btn.textContent = `Feito às ${timeOf(flag.done_at)} ✓`;
    btn.classList.add("done");
    info.textContent = isBedtime && !flag.on_time ? "Marcado depois das 21h." : "";
  } else {
    btn.textContent = "Marcar como feito";
    if (isBedtime && flag.alert) {
      btn.classList.add("late");
      info.textContent = "Já passou das 21h e nem todas as crianças foram marcadas na cama.";
    } else {
      info.textContent = "";
    }
  }
  btn.onclick = async () => {
    await api("/api/flags", {
      method: "POST",
      body: JSON.stringify({ date: todayStr(), key: flag.key, done: !flag.done }),
    });
    await refreshAll();
  };
}

// ---------------------------------------------------------------------
// Visão geral
// ---------------------------------------------------------------------

async function refreshOverview() {
  const data = await api(`/api/overview?date=${todayStr()}`);
  el("streak-number-geral").textContent = data.streak;

  el("ov-bebe-status").textContent = data.bebe.met ? "✅" : "⏳";
  el("ov-bebe-sub").textContent = `Dia ${data.bebe.day_number}/10 do cronograma`;

  el("ov-rapha-status").textContent = data.rapha.met ? "✅" : "⏳";
  el("ov-rapha-sub").textContent = data.rapha.met ? "Dentro da meta" : "Ainda em andamento";

  el("ov-house-fill").style.width = `${data.house.percent}%`;
  el("ov-house-status").textContent = `${data.house.percent}%`;

  renderAlerts("geral-alerts", [...data.bebe.alerts, ...data.rapha.alerts]);

  renderFlag("bedtime-toggle", "bedtime-info", data.bedtime, true);
  renderFlag("selfcare-toggle", "selfcare-info", data.self_care, false);
}

// ---------------------------------------------------------------------
// Semana
// ---------------------------------------------------------------------

async function refreshWeek() {
  const data = await api(`/api/week?date=${todayStr()}`);
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
    const failed = d.failed_checkpoints && d.failed_checkpoints.length ? ` (${d.failed_checkpoints.join(", ")})` : "";
    row.innerHTML = `<span>${fmt.format(dateObj)}${failed}</span><span class="week-badge">${badge}</span>`;
    grid.appendChild(row);
  }
}

// ---------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------

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
    btn.addEventListener("click", () => logQuick(btn.dataset.person, btn.dataset.action));
  });
}

function setupWorkForm() {
  el("work-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = el("work-title").value.trim() || "Compromisso";
    const start = el("work-start").value;
    const end = el("work-end").value;
    if (!start || !end) return;
    await api("/api/work_events", {
      method: "POST",
      body: JSON.stringify({ date: todayStr(), title, start, end }),
    });
    el("work-form").reset();
    refreshPerson("bebe");
  });
}

function setupSettings() {
  el("save-settings").addEventListener("click", async () => {
    const val = el("start-date").value;
    await api("/api/settings", { method: "POST", body: JSON.stringify({ transition_start_date: val }) });
    el("settings-saved").classList.remove("hidden");
    setTimeout(() => el("settings-saved").classList.add("hidden"), 1500);
    refreshAll();
  });
}

async function refreshAll() {
  await Promise.all([
    refreshPerson("bebe"),
    refreshPerson("rapha"),
    refreshHouse(),
    refreshOverview(),
    refreshWeek(),
  ]);
}

function init() {
  setupTabs();
  setupQuickButtons();
  setupWorkForm();
  setupSettings();
  loadSettings();
  refreshAll();
  setInterval(refreshAll, 60000);
}

document.addEventListener("DOMContentLoaded", init);
