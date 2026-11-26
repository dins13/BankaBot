/* Финансовый Telegram Mini App: добавление, история и аналитика операций. */
"use strict";

const tg = window.Telegram ? window.Telegram.WebApp : null;

const PALETTE = [
  "#4f9dff", "#7c6cff", "#37c98a", "#ffb84d", "#ff6b6b", "#43c6db",
  "#e879f9", "#a3e635", "#f97316", "#94a3b8", "#14b8a6", "#f472b6",
];

const state = {
  type: "expense",
  selectedCategory: "",
  categories: { expense: [], income: [] },
  catType: "expense",
  bucket: "auto",
  history: { period: "month", type: "all", category: "" },
  analytics: { period: "month" },
  charts: { category: null, trend: null },
};

let currentTab = "add";
let toastTimer = null;

/* ------------------------------------------------------------------ */
/* Утилиты                                                             */
/* ------------------------------------------------------------------ */

const pad = (n) => String(n).padStart(2, "0");

function isoDate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function rangeFor(period, startEl, endEl) {
  const now = new Date();
  const today = isoDate(now);
  switch (period) {
    case "today":
      return { start: today, end: today };
    case "week": {
      const d = new Date(now);
      const weekday = (d.getDay() + 6) % 7;
      d.setDate(d.getDate() - weekday);
      return { start: isoDate(d), end: today };
    }
    case "month": {
      const d = new Date(now.getFullYear(), now.getMonth(), 1);
      return { start: isoDate(d), end: today };
    }
    case "year": {
      const d = new Date(now.getFullYear(), 0, 1);
      return { start: isoDate(d), end: today };
    }
    case "custom":
      return {
        start: (startEl && startEl.value) || null,
        end: (endEl && endEl.value) || null,
      };
    case "all":
    default:
      return { start: null, end: null };
  }
}

const moneyFormatter = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

function money(value) {
  return moneyFormatter.format(Number(value) || 0) + " ₽";
}

function signedMoney(value) {
  const num = Number(value) || 0;
  if (num > 0) return "+" + money(num);
  if (num < 0) return "−" + money(Math.abs(num));
  return money(0);
}

function formatOpDate(raw) {
  if (!raw) return "";
  const date = new Date(String(raw).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(value) {
  const entities = { 38: "amp", 60: "lt", 62: "gt", 34: "quot", 39: "#39" };
  return String(value ?? "").replace(/[&<>"']/g, (ch) => {
    return "&" + entities[ch.charCodeAt(0)] + ";";
  });
}

function showToast(message, isError = false) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", Boolean(isError));
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}

function haptic(type) {
  try {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred(type);
  } catch (error) {
    /* haptic не критичен */
  }
}

async function api(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (tg && tg.initData) headers["X-Telegram-Init-Data"] = tg.initData;
  const response = await fetch("/api" + path, Object.assign({}, options, { headers }));
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : "Ошибка запроса");
  }
  return data;
}

/* ------------------------------------------------------------------ */
/* Telegram                                                            */
/* ------------------------------------------------------------------ */

function applyTheme() {
  if (!tg || !tg.themeParams) return;
  const params = tg.themeParams;
  const root = document.documentElement.style;
  const mapping = {
    bg_color: "--bg",
    secondary_bg_color: "--card",
    text_color: "--text",
    hint_color: "--muted",
    button_color: "--accent",
    button_text_color: "--accent-text",
    destructive_text_color: "--expense",
  };
  Object.entries(mapping).forEach(([key, variable]) => {
    if (params[key]) root.setProperty(variable, params[key]);
  });
  if (params.secondary_bg_color) root.setProperty("--card-2", params.secondary_bg_color);
  if (params.bg_color) {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", params.bg_color);
  }
}

function initTelegram() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("secondary_bg_color");
    if (tg.setBackgroundColor) tg.setBackgroundColor("bg_color");
    if (tg.onEvent) tg.onEvent("themeChanged", applyTheme);
    applyTheme();
  } catch (error) {
    /* работаем и без Telegram */
  }
}

/* ------------------------------------------------------------------ */
/* Баланс и категории                                                  */
/* ------------------------------------------------------------------ */

function updateBalance(totals) {
  const balance = document.getElementById("balanceValue");
  balance.textContent = signedMoney(totals.balance);
  balance.style.color = totals.balance < 0 ? "#ffd2d2" : "";
  document.getElementById("incomeValue").textContent = money(totals.income);
  document.getElementById("expenseValue").textContent = money(totals.expense);
}

async function loadMe() {
  const data = await api("/me");
  const name = data.user.first_name || data.user.username || "";
  document.getElementById("userName").textContent = name ? "Привет, " + name : "";
  updateBalance(data.totals);
}

async function loadCategories() {
  state.categories = await api("/categories");
  renderChips();
  fillHistoryCategories();
}

function renderChips() {
  const container = document.getElementById("categoryChips");
  const items = state.categories[state.type] || [];
  const names = items.map((item) => item.name);
  if (!state.selectedCategory || !names.includes(state.selectedCategory)) {
    state.selectedCategory = names[0] || "";
  }
  container.innerHTML = "";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip" + (item.name === state.selectedCategory ? " active" : "");
    button.dataset.category = item.name;
    button.innerHTML = `<span>${item.emoji}</span><span>${escapeHtml(item.name)}</span>` +
      (item.count ? `<span class="chip-count">${item.count}</span>` : "");
    button.addEventListener("click", () => {
      state.selectedCategory = item.name;
      const custom = document.getElementById("customCategory");
      if (custom) custom.value = "";
      renderChips();
    });
    container.appendChild(button);
  });
}

function fillHistoryCategories() {
  const select = document.getElementById("historyCategory");
  if (!select) return;
  const previous = select.value;
  const merged = new Map();
  ["expense", "income"].forEach((type) => {
    (state.categories[type] || []).forEach((item) => {
      if (!merged.has(item.name)) merged.set(item.name, item);
    });
  });
  select.innerHTML = '<option value="">Все категории</option>';
  Array.from(merged.values())
    .sort((a, b) => a.name.localeCompare(b.name, "ru"))
    .forEach((item) => {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = `${item.emoji} ${item.name}`;
      select.appendChild(option);
    });
  select.value = merged.has(previous) ? previous : "";
  state.history.category = select.value;
}

/* ------------------------------------------------------------------ */
/* Добавление операции                                                 */
/* ------------------------------------------------------------------ */

function setupForm() {
  const typeSwitch = document.getElementById("typeSwitch");
  typeSwitch.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-type]");
    if (!button) return;
    state.type = button.dataset.type;
    typeSwitch.querySelectorAll("button").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    state.selectedCategory = "";
    renderChips();
  });

  const custom = document.getElementById("customCategory");
  custom.addEventListener("input", () => {
    if (custom.value.trim()) {
      document.querySelectorAll("#categoryChips .chip.active").forEach((chip) => {
        chip.classList.remove("active");
      });
    }
  });

  document.getElementById("opForm").addEventListener("submit", onSubmit);
}

async function onSubmit(event) {
  event.preventDefault();
  const hint = document.getElementById("formHint");
  const submitButton = document.getElementById("submitBtn");
  hint.textContent = "";
  hint.classList.remove("error");

  const amountInput = document.getElementById("amountInput");
  const amount = parseFloat(amountInput.value.replace(",", ".").replace(/\s/g, ""));
  if (!amount || amount <= 0) {
    hint.textContent = "Введите сумму больше нуля";
    hint.classList.add("error");
    return;
  }

  const custom = document.getElementById("customCategory").value.trim().toLowerCase();
  const category = custom || state.selectedCategory;
  if (!category) {
    hint.textContent = "Выберите категорию";
    hint.classList.add("error");
    return;
  }

  const payload = { type: state.type, amount, category };
  const comment = document.getElementById("commentInput").value.trim();
  if (comment) payload.comment = comment;
  const dateValue = document.getElementById("dateInput").value;
  if (dateValue) payload.date = dateValue;

  submitButton.disabled = true;
  try {
    await api("/operations", { method: "POST", body: JSON.stringify(payload) });
    haptic("success");
    showToast("Операция сохранена");
    amountInput.value = "";
    document.getElementById("commentInput").value = "";
    document.getElementById("customCategory").value = "";
    state.selectedCategory = "";
    await refreshAfterChange();
    renderChips();
  } catch (error) {
    haptic("error");
    hint.textContent = error.message;
    hint.classList.add("error");
    showToast(error.message, true);
  } finally {
    submitButton.disabled = false;
  }
}

/* ------------------------------------------------------------------ */
/* История операций                                                    */
/* ------------------------------------------------------------------ */

function historyQuery() {
  const { start, end } = rangeFor(
    state.history.period,
    document.getElementById("historyStart"),
    document.getElementById("historyEnd")
  );
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (state.history.type !== "all") params.set("type", state.history.type);
  if (state.history.category) params.set("category", state.history.category);
  return params;
}

async function loadHistory() {
  try {
    const data = await api("/operations?" + historyQuery().toString());
    renderHistory(data.items, data.totals);
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderHistory(items, totals) {
  const summary = document.getElementById("historySummary");
  summary.innerHTML = `
    <div class="sum-item">
      <span class="sum-label">Доходы</span>
      <span class="sum-value income">${money(totals.income)}</span>
    </div>
    <div class="sum-item">
      <span class="sum-label">Расходы</span>
      <span class="sum-value expense">${money(totals.expense)}</span>
    </div>
    <div class="sum-item">
      <span class="sum-label">Баланс</span>
      <span class="sum-value">${signedMoney(totals.balance)}</span>
    </div>`;

  const list = document.getElementById("historyList");
  if (!items.length) {
    list.innerHTML = '<li class="empty">Операций за выбранный период нет</li>';
    return;
  }
  list.innerHTML = items
    .map((item) => {
      const sign = item.type === "expense" ? "−" : "+";
      const comment = item.comment ? " · " + escapeHtml(item.comment) : "";
      return `
        <li class="op-item" data-id="${item.id}">
          <div class="op-icon">${item.emoji}</div>
          <div class="op-main">
            <div class="op-title">${escapeHtml(item.category)}</div>
            <div class="op-sub">${formatOpDate(item.created_at)}${comment}</div>
          </div>
          <div class="op-amount ${item.type}">${sign}${money(item.amount)}</div>
          <button type="button" class="op-del" data-del="${item.id}" aria-label="Удалить операцию">✕</button>
        </li>`;
    })
    .join("");
}

function setupHistory() {
  const periodSelect = document.getElementById("historyPeriod");
  const customBox = document.getElementById("historyCustom");
  periodSelect.addEventListener("change", () => {
    state.history.period = periodSelect.value;
    customBox.classList.toggle("hidden", periodSelect.value !== "custom");
    loadHistory();
  });

  document.getElementById("historyType").addEventListener("change", (event) => {
    state.history.type = event.target.value;
    loadHistory();
  });

  document.getElementById("historyCategory").addEventListener("change", (event) => {
    state.history.category = event.target.value;
    loadHistory();
  });

  ["historyStart", "historyEnd"].forEach((id) => {
    document.getElementById(id).addEventListener("change", loadHistory);
  });

  document.getElementById("historyList").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-del]");
    if (!button) return;
    const id = button.dataset.del;
    if (!window.confirm("Удалить операцию?")) return;
    try {
      await api("/operations/" + id, { method: "DELETE" });
      haptic("warning");
      showToast("Операция удалена");
      await refreshAfterChange();
    } catch (error) {
      haptic("error");
      showToast(error.message, true);
    }
  });
}

/* ------------------------------------------------------------------ */
/* Аналитика                                                           */
/* ------------------------------------------------------------------ */

function setupAnalytics() {
  const periodSelect = document.getElementById("analyticsPeriod");
  const customBox = document.getElementById("analyticsCustom");
  periodSelect.addEventListener("change", () => {
    state.analytics.period = periodSelect.value;
    customBox.classList.toggle("hidden", periodSelect.value !== "custom");
    loadAnalytics();
  });

  ["analyticsStart", "analyticsEnd"].forEach((id) => {
    document.getElementById(id).addEventListener("change", loadAnalytics);
  });

  document.getElementById("catTypeSwitch").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-cat-type]");
    if (!button) return;
    state.catType = button.dataset.catType;
    document.querySelectorAll("#catTypeSwitch button").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    loadAnalytics();
  });

  document.getElementById("bucketSwitch").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-bucket]");
    if (!button) return;
    state.bucket = button.dataset.bucket;
    document.querySelectorAll("#bucketSwitch button").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    loadAnalytics();
  });
}

async function loadAnalytics() {
  const { start, end } = rangeFor(
    state.analytics.period,
    document.getElementById("analyticsStart"),
    document.getElementById("analyticsEnd")
  );
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (state.bucket !== "auto") params.set("bucket", state.bucket);

  try {
    const data = await api("/stats?" + params.toString());
    renderStatsGrid(data);
    renderCategoryChart(data.categories[state.catType] || []);
    renderTrendChart(data.trend || []);
    renderTopCategories(data.categories.expense || []);
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderStatsGrid(data) {
  const totals = data.totals;
  document.getElementById("statsGrid").innerHTML = `
    <div class="stat">
      <div class="stat-label">Доходы</div>
      <div class="stat-value income">${money(totals.income)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Расходы</div>
      <div class="stat-value expense">${money(totals.expense)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Баланс</div>
      <div class="stat-value">${signedMoney(totals.balance)}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Средний расход в день</div>
      <div class="stat-value">${money(data.avg_expense_per_day)}</div>
    </div>`;
}

function chartTextColor() {
  const value = getComputedStyle(document.documentElement).getPropertyValue("--muted");
  return value.trim() || "#8c98a6";
}

function renderCategoryChart(items) {
  const canvas = document.getElementById("categoryChart");
  const legend = document.getElementById("categoryLegend");

  if (state.charts.category) {
    state.charts.category.destroy();
    state.charts.category = null;
  }

  if (!items.length) {
    legend.innerHTML = '<li class="empty">Нет данных за период</li>';
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }

  const total = items.reduce((sum, item) => sum + item.total, 0) || 1;
  legend.innerHTML = items
    .slice(0, 10)
    .map((item, index) => {
      const share = Math.round((item.total / total) * 100);
      return `<li>
        <span class="dot" style="background:${PALETTE[index % PALETTE.length]}"></span>
        <span class="legend-name">${item.emoji} ${escapeHtml(item.name)}</span>
        <span class="legend-value">${money(item.total)} · ${share}%</span>
      </li>`;
    })
    .join("");

  if (typeof Chart === "undefined") return;

  state.charts.category = new Chart(canvas.getContext("2d"), {
    type: "doughnut",
    data: {
      labels: items.map((item) => item.name),
      datasets: [
        {
          data: items.map((item) => item.total),
          backgroundColor: items.map((_, index) => PALETTE[index % PALETTE.length]),
          borderWidth: 0,
          hoverOffset: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "64%",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `${context.label}: ${money(context.parsed)}`,
          },
        },
      },
    },
  });
}

function renderTrendChart(trend) {
  const canvas = document.getElementById("trendChart");
  if (state.charts.trend) {
    state.charts.trend.destroy();
    state.charts.trend = null;
  }
  if (!trend.length) {
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  if (typeof Chart === "undefined") return;

  const textColor = chartTextColor();
  state.charts.trend = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: trend.map((point) => point.label),
      datasets: [
        {
          label: "Расходы",
          data: trend.map((point) => point.expense),
          borderColor: "#ff6b6b",
          backgroundColor: "rgba(255, 107, 107, 0.14)",
          fill: true,
          tension: 0.35,
          pointRadius: 2,
          borderWidth: 2,
        },
        {
          label: "Доходы",
          data: trend.map((point) => point.income),
          borderColor: "#37c98a",
          backgroundColor: "rgba(55, 201, 138, 0.12)",
          fill: true,
          tension: 0.35,
          pointRadius: 2,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: textColor, boxWidth: 10, boxHeight: 10 } },
        tooltip: {
          callbacks: {
            label: (context) => `${context.dataset.label}: ${money(context.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: textColor, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(140, 152, 166, 0.14)" },
          ticks: {
            color: textColor,
            callback: (value) => moneyFormatter.format(value),
          },
        },
      },
    },
  });
}

function renderTopCategories(items) {
  const container = document.getElementById("topCategories");
  if (!items.length) {
    container.innerHTML = '<li class="empty">Расходов за период нет</li>';
    return;
  }
  const max = Math.max(...items.map((item) => item.total), 1);
  const total = items.reduce((sum, item) => sum + item.total, 0) || 1;
  container.innerHTML = items
    .slice(0, 10)
    .map((item) => {
      const width = Math.max((item.total / max) * 100, 3);
      const share = Math.round((item.total / total) * 100);
      return `<li class="bar-row">
        <div class="bar-top">
          <span class="bar-name">${item.emoji} ${escapeHtml(item.name)}</span>
          <span class="bar-value">${money(item.total)} · ${share}%</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
      </li>`;
    })
    .join("");
}

/* ------------------------------------------------------------------ */
/* Навигация и запуск                                                  */
/* ------------------------------------------------------------------ */

function switchTab(name) {
  currentTab = name;
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "tab-" + name);
  });
  if (name === "history") loadHistory();
  if (name === "analytics") loadAnalytics();
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
}

async function refreshAfterChange() {
  try {
    await Promise.all([loadMe(), loadCategories()]);
  } catch (error) {
    showToast(error.message, true);
  }
  if (currentTab === "history") await loadHistory();
  if (currentTab === "analytics") await loadAnalytics();
}

async function init() {
  initTelegram();
  setupTabs();
  setupForm();
  setupHistory();
  setupAnalytics();

  const dateInput = document.getElementById("dateInput");
  const today = isoDate(new Date());
  dateInput.max = today;
  dateInput.value = today;

  const monthRange = rangeFor("month");
  document.getElementById("historyStart").value = monthRange.start;
  document.getElementById("historyEnd").value = monthRange.end;
  document.getElementById("analyticsStart").value = monthRange.start;
  document.getElementById("analyticsEnd").value = monthRange.end;

  try {
    await loadMe();
    await loadCategories();
    await loadHistory();
  } catch (error) {
    showToast(error.message, true);
  }
}

document.addEventListener("DOMContentLoaded", init);
