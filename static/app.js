"use strict";

// ---- константы ----
const METRICS = [
  { key: "поступило", label: "Поступило", kind: "count" },
  { key: "проработано", label: "Проработано", kind: "count" },
  { key: "трудоемкость", label: "Ср. трудоёмкость", kind: "avg" },
  { key: "длительность", label: "Ср. длительность", kind: "avg" },
  { key: "на_контроле", label: "Ср. на контроле", kind: "avg" },
];
const DIMENSIONS = ["услуга", "продукт", "масштаб", "инициатор", "команда"];
const KPI_CARDS = [
  { key: "поступило", label: "Поступило", kind: "count" },
  { key: "проработано", label: "Проработано", kind: "count" },
  { key: "трудоемкость", label: "Ср. трудоёмкость (ч)", kind: "avg" },
  { key: "длительность", label: "Ср. длительность (раб. дн)", kind: "avg" },
  { key: "на_контроле", label: "Ср. на контроле (раб. дн)", kind: "avg" },
];
const MONTH_NAMES = ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const MONTH_SHORT = ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

// разрез UI -> поле в /api/requests
const DIM_TO_FIELD = {
  "услуга": "service", "продукт": "product", "масштаб": "scale",
  "инициатор": "initiator", "команда": "team",
};

// ---- состояние ----
const state = {
  metric: "поступило",
  dimension: "услуга",
  filters: { месяц: new Set(), услуга: new Set(), продукт: new Set(),
             масштаб: new Set(), инициатор: new Set(), команда: new Set() },
  filterOptions: {},
  matrix: null,
};
let chart = null;
let matrixGen = 0;

// ---- fetch-хелперы ----
async function api(path, params) {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null) continue;
      if (Array.isArray(v)) {
        // повторяющиеся параметры: services=A&services=B (устойчиво к запятым в значениях)
        for (const item of v) if (item !== "" && item !== null && item !== undefined) url.searchParams.append(k, item);
      } else if (v !== "") {
        url.searchParams.set(k, v);
      }
    }
  }
  const r = await fetch(url);
  if (!r.ok) {
    let detail = `Ошибка ${r.status}`;
    try { const b = await r.json(); if (b.detail) detail = b.detail; } catch (_) {}
    throw new Error(detail);
  }
  return r.json();
}

// фильтры (кроме месяца) -> query-параметры API (массивы -> повторяющиеся параметры)
function apiFilterParams() {
  const arr = (s) => Array.from(s);
  return {
    services: arr(state.filters["услуга"]),
    products: arr(state.filters["продукт"]),
    scales: arr(state.filters["масштаб"]),
    teams: arr(state.filters["команда"]),
    initiators: arr(state.filters["инициатор"]),
  };
}

// последний месяц с данными (по totals; подстраховка по ячейкам)
function lastDataMonth() {
  const m = state.matrix;
  if (!m) return null;
  let last = 0;
  if (m.totals) {
    for (const mm of m.months) {
      const v = m.totals[String(mm)];
      if (v !== null && v !== undefined) last = Math.max(last, mm);
    }
  }
  for (const r of m.rows) {
    for (const mm of m.months) {
      const v = cellVal(r, mm);
      if (v !== null && v !== undefined) last = Math.max(last, mm);
    }
  }
  return last || null;
}

// видимые месяцы: фильтр месяца — на клиенте; без фильтра годовой вид
// обрезается по последний месяц актуализации (не показываем пустые будущие месяцы)
function visibleMonths() {
  const all = state.matrix ? state.matrix.months : Array.from({ length: 12 }, (_, i) => i + 1);
  const sel = state.filters["месяц"];
  if (sel.size > 0) return all.filter((m) => sel.has(String(m)));
  const last = lastDataMonth();
  return last ? all.filter((m) => m <= last) : all;
}

function fmtCount(v) { return v === null || v === undefined ? "" : String(Math.round(v)); }
function fmtAvg(v) { return v === null || v === undefined ? "" : Number(v).toFixed(1); }
// «Ср. длительность» показываем целым (значения уже округлены вверх на бэкенде)
function metricFmt(metricKey) {
  const m = METRICS.find((x) => x.key === metricKey);
  const kind = m ? m.kind : "count";
  if (kind === "count" || metricKey === "длительность") return fmtCount;
  return fmtAvg;
}
function fmtKpi(v, kind, key) {
  if (v === null || v === undefined) return "—";
  if (kind === "count" || key === "длительность") return String(Math.round(v));
  return Number(v).toFixed(1);
}
function currentKind() {
  const m = METRICS.find((x) => x.key === state.metric);
  return m ? m.kind : "count";
}

function showToast(msg, isError) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " toast--error" : "");
  t.hidden = false;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { t.hidden = true; }, isError ? 8000 : 4000);
}

// ---- статус загрузки ----
async function loadStatus() {
  const line = document.getElementById("status-line");
  try {
    const { upload } = await api("/api/status");
    if (!upload) { line.textContent = "Данные не загружены"; return; }
    let when = upload.uploaded_at;
    const d = new Date(when);
    if (!isNaN(d)) {
      when = d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit",
        year: "numeric", hour: "2-digit", minute: "2-digit" });
    }
    line.textContent = `Последняя загрузка: ${upload.filename}, ${upload.row_count} строк, ${upload.uploaded_by || "—"}, ${when}`;
  } catch (e) {
    line.textContent = "Не удалось получить статус: " + e.message;
  }
}

// ---- загрузка файла ----
async function uploadFile(file) {
  const btn = document.getElementById("upload-btn");
  btn.disabled = true;
  const origText = btn.textContent;
  btn.textContent = "Загрузка…";
  const fd = new FormData();
  fd.append("file", file);
  fd.append("uploaded_by", "Веб-интерфейс");
  try {
    let r;
    try {
      r = await fetch("/api/upload", { method: "POST", body: fd });
    } catch (e) {
      showToast("Сетевая ошибка при загрузке: " + e.message, true);
      return;
    }
    if (!r.ok) {
      let detail = `Ошибка ${r.status}`;
      try { const b = await r.json(); if (b.detail) detail = b.detail; } catch (_) {}
      showToast(detail, true);
      return;
    }
    const body = await r.json();
    showToast(`Файл загружен: ${body.row_count} строк`);
    await loadStatus();
    await loadFilters();
    await refreshAll();
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

// ---- KPI ----
async function renderKpi() {
  const el = document.getElementById("kpi");
  let s;
  try { s = await api("/api/summary", apiFilterParams()); }
  catch (e) { el.innerHTML = `<div class="empty">KPI недоступны: ${e.message}</div>`; return; }
  el.innerHTML = KPI_CARDS.map((c) =>
    `<div class="kpi__card"><div class="kpi__label">${c.label}</div>` +
    `<div class="kpi__value">${fmtKpi(s[c.key], c.kind, c.key)}</div></div>`).join("");
}

// ---- фильтры ----
async function loadFilters() {
  try { state.filterOptions = await api("/api/filters"); }
  catch (e) { showToast("Не удалось загрузить фильтры: " + e.message, true); state.filterOptions = {}; }
  renderFilters();
}

function renderFilters() {
  const row = document.getElementById("filters-row");
  row.innerHTML = "";

  // месяц
  const monthOpts = Array.from({ length: 12 }, (_, i) => ({ value: String(i + 1), label: MONTH_NAMES[i + 1] }));
  row.appendChild(buildFilter("месяц", "Месяц", monthOpts));

  // 5 разрезов
  for (const dim of DIMENSIONS) {
    const opts = (state.filterOptions[dim] || []).map((v) => ({ value: v, label: v }));
    const label = dim.charAt(0).toUpperCase() + dim.slice(1);
    row.appendChild(buildFilter(dim, label, opts));
  }
}

function buildFilter(key, label, options) {
  const wrap = document.createElement("div");
  wrap.className = "filter";
  const selected = state.filters[key];

  const lab = document.createElement("span");
  lab.className = "filter__label";
  lab.textContent = label;
  wrap.appendChild(lab);

  const btn = document.createElement("button");
  btn.className = "filter__btn";
  btn.type = "button";
  btn.textContent = selected.size ? `${label}: ${selected.size}` : "Все";
  wrap.appendChild(btn);

  const menu = document.createElement("div");
  menu.className = "filter__menu";
  menu.hidden = true;

  for (const opt of options) {
    const row = document.createElement("label");
    row.className = "filter__opt";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = selected.has(opt.value);
    cb.addEventListener("change", () => {
      if (cb.checked) selected.add(opt.value); else selected.delete(opt.value);
      btn.textContent = selected.size ? `${label}: ${selected.size}` : "Все";
      onFiltersChanged(key);
    });
    const span = document.createElement("span");
    span.textContent = opt.label;
    row.appendChild(cb);
    row.appendChild(span);
    menu.appendChild(row);
  }
  if (!options.length) {
    const e = document.createElement("div");
    e.className = "filter__opt";
    e.textContent = "нет значений";
    menu.appendChild(e);
  }
  wrap.appendChild(menu);

  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    document.querySelectorAll(".filter__menu").forEach((m) => { if (m !== menu) m.hidden = true; });
    menu.hidden = !menu.hidden;
  });
  menu.addEventListener("click", (ev) => ev.stopPropagation());
  return wrap;
}

// месяц -> только перерисовка (клиентский фильтр); прочие -> запрос API
function onFiltersChanged(key) {
  if (key === "месяц") { renderTable(); renderChart(); }
  else { renderKpi(); reloadMatrix(); }
}

function resetFilters() {
  for (const k of Object.keys(state.filters)) state.filters[k].clear();
  renderFilters();
  renderKpi();
  reloadMatrix();
}

// ---- табы (показатели) ----
function renderTabs() {
  const el = document.getElementById("tabs");
  el.innerHTML = "";
  for (const m of METRICS) {
    const b = document.createElement("button");
    b.className = "tab" + (m.key === state.metric ? " tab--active" : "");
    b.textContent = m.label;
    b.addEventListener("click", () => {
      state.metric = m.key;
      renderTabs();
      reloadMatrix();
    });
    el.appendChild(b);
  }
}

// ---- сегментированный выбор разреза ----
function renderDims() {
  const el = document.getElementById("dims");
  el.innerHTML = "";
  const lab = document.createElement("span");
  lab.className = "dims__label";
  lab.textContent = "Разрез по:";
  el.appendChild(lab);

  const seg = document.createElement("div");
  seg.className = "seg";
  for (const d of DIMENSIONS) {
    const b = document.createElement("button");
    b.className = "seg__btn" + (d === state.dimension ? " seg__btn--active" : "");
    b.textContent = d.charAt(0).toUpperCase() + d.slice(1);
    b.addEventListener("click", () => {
      state.dimension = d;
      renderDims();
      reloadMatrix();
    });
    seg.appendChild(b);
  }
  el.appendChild(seg);
}

// ---- данные матрицы ----
async function reloadMatrix() {
  const gen = ++matrixGen;
  try {
    const result = await api("/api/metrics",
      Object.assign({ metric: state.metric, dimension: state.dimension }, apiFilterParams()));
    if (gen !== matrixGen) return; // более новый запрос уже выполняется — игнорируем устаревший ответ
    state.matrix = result;
  } catch (e) {
    if (gen !== matrixGen) return;
    state.matrix = null;
    document.getElementById("matrix").innerHTML =
      `<tbody><tr><td class="empty">Не удалось загрузить данные: ${e.message}</td></tr></tbody>`;
    if (chart) { chart.destroy(); chart = null; }
    return;
  }
  renderTable();
  renderChart();
}

function cellVal(rowName, month) {
  const m = state.matrix;
  if (!m || !m.values[rowName]) return null;
  const v = m.values[rowName][String(month)];
  return v === undefined ? null : v;
}

// «ВСЕГО» по месяцу берём с бэкенда (totals): для count — количество запросов,
// для средних — честное среднее ПО ВСЕМ запросам месяца, а не среднее из средних по разрезам.
function totalForMonth(month) {
  const m = state.matrix;
  if (!m || !m.totals) return null;
  const v = m.totals[String(month)];
  return v === undefined ? null : v;
}

// ---- таблица ----
function renderTable() {
  const table = document.getElementById("matrix");
  const m = state.matrix;
  const months = visibleMonths();
  const fmt = metricFmt(state.metric);

  if (!m || !m.rows.length || !months.length) {
    table.innerHTML = `<tbody><tr><td class="empty">Нет данных для отображения</td></tr></tbody>`;
    return;
  }

  let head = "<thead><tr><th>" +
    state.dimension.charAt(0).toUpperCase() + state.dimension.slice(1) + "</th>";
  for (const mm of months) head += `<th>${MONTH_SHORT[mm]}</th>`;
  head += "</tr></thead>";

  let body = "<tbody>";
  for (const r of m.rows) {
    body += `<tr><td>${escapeHtml(r)}</td>`;
    for (const mm of months) {
      const v = cellVal(r, mm);
      const txt = fmt(v);
      const cls = txt !== "" ? ' class="cell--clickable"' : "";
      const attrs = txt !== "" ? ` data-row="${escapeAttr(r)}" data-month="${mm}"` : "";
      body += `<td${cls}${attrs}>${txt}</td>`;
    }
    body += "</tr>";
  }
  // ВСЕГО
  body += `<tr class="total-row"><td>ВСЕГО</td>`;
  for (const mm of months) body += `<td>${fmt(totalForMonth(mm))}</td>`;
  body += "</tr></tbody>";

  table.innerHTML = head + body;

  table.querySelectorAll("td.cell--clickable").forEach((td) => {
    td.addEventListener("click", () =>
      openDrilldown(td.getAttribute("data-row"), parseInt(td.getAttribute("data-month"), 10)));
  });
}

// ---- график ----
function renderChart() {
  const m = state.matrix;
  const months = visibleMonths();
  const ctx = document.getElementById("chart");
  if (chart) { chart.destroy(); chart = null; }
  if (!m || !months.length) return;

  const kind = currentKind();
  const type = kind === "count" ? "bar" : "line";
  const labels = months.map((mm) => MONTH_SHORT[mm]);

  // ВСЕГО по месяцам + по одной серии на топ-строки (до 6, по сумме/среднему)
  const accentColors = ["#1f3a5f", "#3f7cac", "#7aa6c2", "#c98b3e", "#5a8f69", "#9b6a9e", "#b3565a"];
  const totalSeries = {
    label: "ВСЕГО",
    data: months.map((mm) => totalForMonth(mm)),
    borderColor: accentColors[0],
    backgroundColor: type === "bar" ? "rgba(31,58,95,.75)" : "rgba(31,58,95,.15)",
    borderWidth: 2,
    tension: .25,
    spanGaps: true,
  };

  const ranked = m.rows.slice().map((r) => {
    const vals = months.map((mm) => cellVal(r, mm)).filter((v) => v !== null && v !== undefined);
    const score = vals.reduce((a, b) => a + b, 0);
    return { r, score };
  }).sort((a, b) => b.score - a.score).slice(0, 6);

  const rowSeries = ranked.map((item, i) => ({
    label: item.r,
    data: months.map((mm) => cellVal(item.r, mm)),
    borderColor: accentColors[(i + 1) % accentColors.length],
    backgroundColor: type === "bar"
      ? accentColors[(i + 1) % accentColors.length]
      : "rgba(0,0,0,0)",
    borderWidth: type === "bar" ? 0 : 2,
    tension: .25,
    spanGaps: true,
  }));

  chart = new Chart(ctx, {
    type,
    data: { labels, datasets: [totalSeries, ...rowSeries] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, font: { size: 11 } } },
        title: {
          display: true,
          text: METRICS.find((x) => x.key === state.metric).label + " по месяцам",
          color: "#1c2430",
        },
      },
      scales: { y: { beginAtZero: true } },
    },
  });
}

// ---- drill-down ----
async function openDrilldown(rowName, month) {
  const overlay = document.getElementById("drill-overlay");
  const title = document.getElementById("drill-title");
  const tbl = document.getElementById("drill-table");
  overlay.hidden = false;
  title.textContent = `${rowName} · ${MONTH_NAMES[month]}`;
  tbl.innerHTML = `<tbody><tr><td class="empty">Загрузка…</td></tr></tbody>`;

  let rows;
  try {
    rows = await api("/api/requests", Object.assign({
      metric: state.metric, dimension: state.dimension, value: rowName, month,
    }, apiFilterParams()));
  } catch (e) {
    tbl.innerHTML = `<tbody><tr><td class="empty">Ошибка: ${e.message}</td></tr></tbody>`;
    return;
  }
  if (!rows.length) {
    tbl.innerHTML = `<tbody><tr><td class="empty">Запросы не найдены</td></tr></tbody>`;
    return;
  }
  const kind = currentKind();
  const valFmt = kind === "count" ? fmtCount : fmtAvg;
  let html = "<thead><tr><th>Запрос</th><th>Организация</th><th>Услуга</th>" +
    "<th>Команда</th><th>Статус</th><th>Дата начала</th><th>Значение</th></tr></thead><tbody>";
  for (const it of rows) {
    html += "<tr>" +
      `<td>${escapeHtml(it.request)}</td>` +
      `<td>${escapeHtml(it.org)}</td>` +
      `<td>${escapeHtml(it.service)}</td>` +
      `<td>${escapeHtml(it.team)}</td>` +
      `<td>${escapeHtml(it.status)}</td>` +
      `<td>${escapeHtml(it.date_start || "")}</td>` +
      `<td>${valFmt(it.value)}</td>` +
      "</tr>";
  }
  html += "</tbody>";
  tbl.innerHTML = html;
}

function closeDrilldown() { document.getElementById("drill-overlay").hidden = true; }

// ---- экспорт ----
function exportExcel() {
  const url = new URL("/api/export", window.location.origin);
  url.searchParams.set("dimension", state.dimension);
  const p = apiFilterParams();
  for (const [k, vals] of Object.entries(p)) for (const v of vals) if (v) url.searchParams.append(k, v);
  const selMonths = state.filters["месяц"];
  if (selMonths.size > 0) {
    url.searchParams.set("months", Array.from(selMonths).map(Number).sort((a, b) => a - b).join(","));
  }
  window.location.href = url.toString();
}

// ---- утилиты ----
function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }

async function refreshAll() {
  await renderKpi();
  await reloadMatrix();
}

// ---- init ----
function bindEvents() {
  document.getElementById("upload-btn").addEventListener("click",
    () => document.getElementById("file-input").click());
  document.getElementById("file-input").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) uploadFile(f);
    e.target.value = "";
  });
  document.getElementById("export-btn").addEventListener("click", exportExcel);
  document.getElementById("reset-btn").addEventListener("click", resetFilters);
  document.getElementById("drill-close").addEventListener("click", closeDrilldown);
  document.getElementById("drill-overlay").addEventListener("click", (e) => {
    if (e.target.id === "drill-overlay") closeDrilldown();
  });
  document.addEventListener("click", () =>
    document.querySelectorAll(".filter__menu").forEach((m) => { m.hidden = true; }));
}

async function init() {
  bindEvents();
  renderTabs();
  renderDims();
  await loadStatus();
  await loadFilters();
  await refreshAll();
}

document.addEventListener("DOMContentLoaded", init);
