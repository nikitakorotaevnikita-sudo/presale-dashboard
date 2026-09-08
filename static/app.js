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
// единицы измерения показателей (для заголовков таблицы и графика)
const METRIC_UNIT = {
  "трудоемкость": "в часах",
  "длительность": "в раб. днях",
  "на_контроле": "в раб. днях",
};
// пояснения к значениям разреза «Масштаб» (по числу пользователей)
const SCALE_HINTS = [
  { match: /ФОИВ/i, text: "от 1000 пользователей" },
  { match: /РОИВ/i, text: "от 500 пользователей" },
  { match: /друг/i, text: "до 500 пользователей" },
];
// подпись значения с пояснением (для «Масштаба»)
function valueLabel(value) {
  if (state.dimension === "масштаб") {
    const h = SCALE_HINTS.find((x) => x.match.test(value));
    if (h) return `${value} — ${h.text}`;
  }
  return value;
}
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
// Месяцы, исключённые из дашборда (совпадает с исключением на бэкенде).
const EXCLUDED_MONTHS = new Set([12]);

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
  for (const mm of m.months) {
    if (EXCLUDED_MONTHS.has(mm)) continue;
    let has = m.totals && m.totals[String(mm)] !== null && m.totals[String(mm)] !== undefined;
    if (!has) has = m.rows.some((r) => { const v = cellVal(r, mm); return v !== null && v !== undefined; });
    if (has) last = Math.max(last, mm);
  }
  return last || null;
}

// видимые месяцы: фильтр месяца — на клиенте; без фильтра годовой вид
// обрезается по последний месяц актуализации (не показываем пустые будущие месяцы)
function visibleMonths() {
  const base = state.matrix ? state.matrix.months : Array.from({ length: 12 }, (_, i) => i + 1);
  const all = base.filter((m) => !EXCLUDED_MONTHS.has(m));
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

  // месяц (без исключённых, напр. декабря)
  const monthOpts = Array.from({ length: 12 }, (_, i) => i + 1)
    .filter((m) => !EXCLUDED_MONTHS.has(m))
    .map((m) => ({ value: String(m), label: MONTH_NAMES[m] }));
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
  const isCount = currentKind() === "count";
  const TCOL = ' style="font-weight:600;border-left:2px solid #cdd6e4"';

  if (!m || !m.rows.length || !months.length) {
    table.innerHTML = `<tbody><tr><td class="empty">Нет данных для отображения</td></tr></tbody>`;
    return;
  }

  // «Всего» по строке: для count — сумма по месяцам, для средних — среднее непустых
  const aggregate = (vals) => {
    const xs = vals.filter((v) => v !== null && v !== undefined);
    if (!xs.length) return null;
    const sum = xs.reduce((a, b) => a + b, 0);
    return isCount ? sum : sum / xs.length;
  };
  const rowTotal = (r) => aggregate(months.map((mm) => cellVal(r, mm)));
  const grandTotal = () => aggregate(months.map((mm) => totalForMonth(mm)));

  let head = "<thead><tr><th>" +
    state.dimension.charAt(0).toUpperCase() + state.dimension.slice(1) + "</th>";
  for (const mm of months) head += `<th>${MONTH_SHORT[mm]}</th>`;
  head += `<th${TCOL}>Всего</th>`;
  head += "</tr></thead>";

  let body = "<tbody>";
  for (const r of m.rows) {
    body += `<tr><td>${escapeHtml(valueLabel(r))}</td>`;
    for (const mm of months) {
      const v = cellVal(r, mm);
      const txt = fmt(v);
      const cls = txt !== "" ? ' class="cell--clickable"' : "";
      const attrs = txt !== "" ? ` data-row="${escapeAttr(r)}" data-month="${mm}"` : "";
      body += `<td${cls}${attrs}>${txt}</td>`;
    }
    body += `<td${TCOL}>${fmt(rowTotal(r))}</td>`;
    body += "</tr>";
  }
  // ВСЕГО
  body += `<tr class="total-row"><td>ВСЕГО</td>`;
  for (const mm of months) body += `<td>${fmt(totalForMonth(mm))}</td>`;
  body += `<td${TCOL}>${fmt(grandTotal())}</td>`;
  body += "</tr></tbody>";

  const label = METRICS.find((x) => x.key === state.metric).label;
  const unit = METRIC_UNIT[state.metric];
  const caption = `<caption style="caption-side:top;text-align:left;font-weight:600;padding:6px 2px;color:#1c2430">` +
    `${escapeHtml(unit ? label + " " + unit : label)}</caption>`;

  table.innerHTML = caption + head + body;

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
    hidden: true,  // по умолчанию скрыта; включается кликом по легенде
  };

  const ranked = m.rows.slice().map((r) => {
    const vals = months.map((mm) => cellVal(r, mm)).filter((v) => v !== null && v !== undefined);
    const score = vals.reduce((a, b) => a + b, 0);
    return { r, score };
  }).sort((a, b) => b.score - a.score).slice(0, 6);

  const rowSeries = ranked.map((item, i) => ({
    label: valueLabel(item.r),
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
          text: (() => {
            const label = METRICS.find((x) => x.key === state.metric).label;
            const unit = METRIC_UNIT[state.metric];
            return unit ? `${label} ${unit}` : `${label} по месяцам`;
          })(),
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
      `<td>${requestCell(it.request, it.link)}</td>` +
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

// Название запроса как ссылка. Приоритет — URL из гиперссылки ячейки (поле link);
// если его нет, ищем http(s)-ссылку прямо в тексте (запасной вариант).
function requestCell(text, link) {
  const esc = escapeHtml(text == null ? "" : text);
  if (link) {
    return `<a href="${escapeAttr(link)}" target="_blank" rel="noopener noreferrer">${esc}</a>`;
  }
  return esc.replace(/https?:\/\/[^\s<]+/g, (u) =>
    `<a href="${u}" target="_blank" rel="noopener noreferrer">🔗 Открыть</a>`);
}

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

// ---- верхние вкладки (Дашборд / ИИ-аналитик / Бэкофис) ----
function switchView(view) {
  for (const v of ["dashboard", "ai", "backoffice"]) {
    document.getElementById("view-" + v).hidden = v !== view;
  }
  document.querySelectorAll(".topnav__btn").forEach((b) =>
    b.classList.toggle("topnav__btn--active", b.dataset.view === view));
  if (view === "ai") initAi();
  if (view === "backoffice") loadLlmSettings();
}
document.getElementById("top-nav").addEventListener("click", (e) => {
  const b = e.target.closest(".topnav__btn");
  if (b) switchView(b.dataset.view);
});

// ---- Бэкофис: настройки LLM ----
async function loadLlmSettings() {
  try {
    const c = await api("/api/settings/llm");
    document.getElementById("llm-provider").value = c.provider || "local";
    document.getElementById("llm-base-url").value = c.base_url || "";
    document.getElementById("llm-model").value = c.model || "";
    document.getElementById("llm-token").placeholder =
      c.token ? c.token + " (сохранён — оставьте пустым, чтобы не менять)" : "введите токен";
  } catch (e) { document.getElementById("llm-status").textContent = "Ошибка: " + e.message; }
}
document.getElementById("llm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    provider: document.getElementById("llm-provider").value,
    base_url: document.getElementById("llm-base-url").value,
    model: document.getElementById("llm-model").value,
    token: document.getElementById("llm-token").value,
  };
  try {
    await fetch("/api/settings/llm", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then((r) => { if (!r.ok) throw new Error("Ошибка сохранения"); });
    document.getElementById("llm-token").value = "";
    document.getElementById("llm-status").textContent = "Сохранено";
    loadLlmSettings();
  } catch (e) { document.getElementById("llm-status").textContent = e.message; }
});
document.getElementById("llm-test").addEventListener("click", async () => {
  const s = document.getElementById("llm-status");
  s.textContent = "Проверка…";
  try {
    const r = await fetch("/api/llm/test", { method: "POST" }).then((x) => x.json());
    s.textContent = r.message;
  } catch (e) { s.textContent = "Ошибка: " + e.message; }
});

// ---- ИИ-аналитик: чат со стримингом ----
let aiInited = false;
const chatHistory = [];  // {role, content}

async function initAi() {
  if (aiInited) return;
  aiInited = true;
  try {
    const { suggestions } = await api("/api/chat/suggestions");
    const box = document.getElementById("chat-suggestions");
    box.innerHTML = "";
    for (const s of suggestions) {
      const b = document.createElement("button");
      b.className = "suggestion";
      b.textContent = s;
      b.addEventListener("click", () => sendChat(s));
      box.appendChild(b);
    }
  } catch (_) {}
}

function appendBubble(role, text) {
  const log = document.getElementById("chat-log");
  const d = document.createElement("div");
  d.className = "bubble bubble--" + role;
  d.textContent = text;
  log.appendChild(d);
  log.scrollTop = log.scrollHeight;
  return d;
}

async function streamInto(url, body, bubble) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = "Ошибка " + r.status;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    bubble.textContent = msg;
    return "";
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let acc = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    acc += dec.decode(value, { stream: true });
    bubble.textContent = acc;
    document.getElementById("chat-log").scrollTop = 1e9;
  }
  return acc;
}

async function sendChat(text) {
  const input = document.getElementById("chat-input");
  const q = text || input.value.trim();
  if (!q) return;
  input.value = "";
  appendBubble("user", q);
  chatHistory.push({ role: "user", content: q });
  const bubble = appendBubble("assistant", "…");
  const answer = await streamInto("/api/chat", { messages: chatHistory }, bubble);
  if (answer) chatHistory.push({ role: "assistant", content: answer });
}

document.getElementById("chat-form").addEventListener("submit", (e) => {
  e.preventDefault(); sendChat();
});
document.getElementById("analyze-btn").addEventListener("click", async () => {
  appendBubble("user", "Анализ узких мест");
  const bubble = appendBubble("assistant", "…");
  await streamInto("/api/analyze", {}, bubble);
});
