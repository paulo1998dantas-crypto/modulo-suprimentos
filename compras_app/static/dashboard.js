(() => {
  "use strict";

  const state = { period: "month", status: "all" };
  const statusLabels = {
    all: "Todos os status",
    "os-active": "O.S. ativas",
    "os-closed": "O.S. encerradas",
    "oc-active": "O.C. ativas",
    "oc-closed": "O.C. encerradas",
    cancelled: "Canceladas",
  };

  function documents() {
    return window.suprimentosDashboardData && Array.isArray(window.suprimentosDashboardData.documentos)
      ? window.suprimentosDashboardData.documentos
      : [];
  }

  function isoDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function parseDate(value) {
    const parts = String(value || "").split("-").map(Number);
    if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function formatDate(value) {
    const date = parseDate(value);
    return date ? new Intl.DateTimeFormat("pt-BR").format(date) : "-";
  }

  function currency(value) {
    return new Intl.NumberFormat("pt-BR", {
      style: "currency",
      currency: "BRL",
    }).format(Number(value || 0));
  }

  function periodBounds(period) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    if (period === "all") return { start: "", end: "" };
    if (period === "today") {
      const value = isoDate(today);
      return { start: value, end: value };
    }
    if (period === "week") {
      const start = new Date(today);
      const weekday = start.getDay() || 7;
      start.setDate(start.getDate() - weekday + 1);
      return { start: isoDate(start), end: isoDate(today) };
    }
    return {
      start: isoDate(new Date(today.getFullYear(), today.getMonth(), 1)),
      end: isoDate(today),
    };
  }

  function periodDocuments() {
    const start = document.getElementById("dashboard_date_start")?.value || "";
    const end = document.getElementById("dashboard_date_end")?.value || "";
    return documents().filter((doc) => {
      const date = String(doc.data || "");
      if (start && (!date || date < start)) return false;
      if (end && (!date || date > end)) return false;
      return true;
    });
  }

  function isActive(doc) {
    return !["concluido", "cancelado"].includes(String(doc.status || "emitido"));
  }

  function matchesStatus(doc) {
    if (state.status === "all") return true;
    if (state.status === "cancelled") return doc.status === "cancelado";
    if (state.status === "os-active") return doc.tipo === "os" && isActive(doc);
    if (state.status === "os-closed") return doc.tipo === "os" && doc.status === "concluido";
    if (state.status === "oc-active") return doc.tipo === "oc" && isActive(doc);
    if (state.status === "oc-closed") return doc.tipo === "oc" && doc.status === "concluido";
    return true;
  }

  function groupByDate(items, type, sumTotal) {
    const grouped = new Map();
    items.forEach((doc) => {
      if (doc.tipo !== type || doc.status === "cancelado" || !doc.data) return;
      const value = sumTotal ? Number(doc.total || 0) : 1;
      grouped.set(doc.data, (grouped.get(doc.data) || 0) + value);
    });
    return Array.from(grouped.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-12)
      .map(([date, value]) => ({ label: formatDate(date).slice(0, 5), value }));
  }

  function sortRecent(items) {
    return [...items].sort((a, b) => {
      const dateCompare = String(b.data || "").localeCompare(String(a.data || ""));
      if (dateCompare) return dateCompare;
      const orderCompare = String(b.ordem || "").localeCompare(String(a.ordem || ""));
      if (orderCompare) return orderCompare;
      return String(b.numero || "").localeCompare(String(a.numero || ""), "pt-BR", { numeric: true });
    });
  }

  function statusInfo(status) {
    const normalized = ["emitido", "rascunho", "concluido", "cancelado"].includes(status)
      ? status
      : "emitido";
    const labels = {
      emitido: "Emitido",
      rascunho: "Rascunho",
      concluido: "Concluído",
      cancelado: "Cancelado",
    };
    return { value: normalized, label: labels[normalized] };
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = String(value);
  }

  function renderLatest(tbodyId, countId, items, type) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;
    const rows = sortRecent(items.filter((doc) => doc.tipo === type)).slice(0, 5);
    tbody.replaceChildren();
    setText(countId, `${rows.length} registro(s)`);
    if (!rows.length) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.textContent = "Nenhum documento no período.";
      row.appendChild(cell);
      tbody.appendChild(row);
      return;
    }
    rows.forEach((doc) => {
      const row = document.createElement("tr");
      const dateCell = document.createElement("td");
      dateCell.textContent = formatDate(doc.data);
      const numberCell = document.createElement("td");
      const numberButton = document.createElement("button");
      numberButton.type = "button";
      numberButton.className = "link-button";
      numberButton.textContent = doc.numero || "-";
      numberButton.addEventListener("click", () => {
        document.querySelector(`.topbar .tab-btn[data-tab="tab-gestao-${type}"]`)?.click();
        if (type === "os") visualizarHistoricoOS(doc.id);
        else visualizarHistoricoOC(doc.id);
      });
      numberCell.appendChild(numberButton);
      const nameCell = document.createElement("td");
      nameCell.textContent = doc.nome || "-";
      const statusCell = document.createElement("td");
      const info = statusInfo(doc.status);
      const badge = document.createElement("span");
      badge.className = `status-badge ${info.value}`;
      badge.textContent = info.label;
      statusCell.appendChild(badge);
      const detailCell = document.createElement("td");
      detailCell.textContent = type === "os" ? `${doc.itens || 0} item(ns)` : currency(doc.total);
      [dateCell, numberCell, nameCell, statusCell, detailCell].forEach((cell) => row.appendChild(cell));
      tbody.appendChild(row);
    });
  }

  function renderRanking(items) {
    const container = document.getElementById("dashboard_top_clients");
    if (!container) return;
    const counts = new Map();
    items.forEach((doc) => {
      if (doc.tipo !== "os" || doc.status === "cancelado" || !String(doc.nome || "").trim()) return;
      const name = String(doc.nome).trim().replace(/\s+/g, " ");
      const key = name.toLocaleUpperCase("pt-BR");
      const current = counts.get(key) || { name, value: 0 };
      current.value += 1;
      counts.set(key, current);
    });
    const ranking = Array.from(counts.values())
      .sort((a, b) => b.value - a.value || a.name.localeCompare(b.name))
      .slice(0, 5);
    container.replaceChildren();
    if (!ranking.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "Sem clientes no período.";
      container.appendChild(empty);
      return;
    }
    const max = Math.max(...ranking.map((item) => item.value), 1);
    ranking.forEach(({ name, value }) => {
      const row = document.createElement("div");
      row.className = "ranking-row";
      const label = document.createElement("div");
      label.className = "ranking-label";
      label.title = name;
      label.textContent = name;
      const track = document.createElement("div");
      track.className = "ranking-track";
      const fill = document.createElement("div");
      fill.className = "ranking-fill";
      fill.style.width = `${(value / max) * 100}%`;
      track.appendChild(fill);
      const amount = document.createElement("div");
      amount.className = "ranking-value";
      amount.textContent = String(value);
      [label, track, amount].forEach((element) => row.appendChild(element));
      container.appendChild(row);
    });
  }

  function renderStatusOverview(items) {
    const container = document.getElementById("dashboard_status_overview");
    if (!container) return;
    const rows = [
      ["O.S. ativas", items.filter((doc) => doc.tipo === "os" && isActive(doc)).length],
      ["O.S. encerradas", items.filter((doc) => doc.tipo === "os" && doc.status === "concluido").length],
      ["O.C. ativas", items.filter((doc) => doc.tipo === "oc" && isActive(doc)).length],
      ["O.C. encerradas", items.filter((doc) => doc.tipo === "oc" && doc.status === "concluido").length],
      ["Canceladas", items.filter((doc) => doc.status === "cancelado").length],
    ];
    const max = Math.max(...rows.map(([, value]) => value), 1);
    container.replaceChildren();
    rows.forEach(([name, value]) => {
      const row = document.createElement("div");
      row.className = "status-overview-row";
      const label = document.createElement("div");
      label.className = "status-overview-label";
      label.textContent = name;
      const track = document.createElement("div");
      track.className = "status-overview-track";
      const fill = document.createElement("div");
      fill.className = "status-overview-fill";
      fill.style.width = `${(value / max) * 100}%`;
      track.appendChild(fill);
      const amount = document.createElement("div");
      amount.className = "status-overview-value";
      amount.textContent = String(value);
      [label, track, amount].forEach((element) => row.appendChild(element));
      container.appendChild(row);
    });
  }

  function render() {
    const periodItems = periodDocuments();
    const focusedItems = periodItems.filter(matchesStatus);
    setText("metric_os_active", periodItems.filter((doc) => doc.tipo === "os" && isActive(doc)).length);
    setText("metric_os_closed", periodItems.filter((doc) => doc.tipo === "os" && doc.status === "concluido").length);
    setText("metric_oc_active", periodItems.filter((doc) => doc.tipo === "oc" && isActive(doc)).length);
    setText("metric_oc_closed", periodItems.filter((doc) => doc.tipo === "oc" && doc.status === "concluido").length);
    setText("metric_cancelled", periodItems.filter((doc) => doc.status === "cancelado").length);
    const purchaseTotal = periodItems
      .filter((doc) => doc.tipo === "oc" && doc.status !== "cancelado")
      .reduce((sum, doc) => sum + Number(doc.total || 0), 0);
    setText("metric_purchase_total", currency(purchaseTotal));

    const ocSeries = groupByDate(focusedItems, "oc", true);
    const osSeries = groupByDate(focusedItems, "os", false);
    setTimeout(() => {
      renderBarChart("chart-compras", ocSeries.map((item) => item.label), ocSeries.map((item) => item.value), "#087f78", "R$ ");
      renderBarChart("chart-os", osSeries.map((item) => item.label), osSeries.map((item) => item.value), "#d4663f", "");
    }, 0);
    renderRanking(focusedItems);
    renderStatusOverview(periodItems);
    renderLatest("dashboard_latest_os", "latest_os_count", focusedItems, "os");
    renderLatest("dashboard_latest_oc", "latest_oc_count", focusedItems, "oc");

    const start = document.getElementById("dashboard_date_start")?.value || "";
    const end = document.getElementById("dashboard_date_end")?.value || "";
    const range = start || end ? `${formatDate(start)} a ${formatDate(end)}` : "Todo o histórico";
    setText("dashboard_period_summary", `${range} · ${periodItems.length} documento(s)`);
    setText("dashboard_status_filter", statusLabels[state.status] || statusLabels.all);
    const clear = document.getElementById("dashboard_clear_status");
    if (clear) clear.hidden = state.status === "all";
    document.querySelectorAll("[data-dashboard-status]").forEach((button) => {
      button.classList.toggle("active", button.dataset.dashboardStatus === state.status);
    });
  }

  function setPeriod(period) {
    state.period = period;
    const bounds = periodBounds(period);
    const start = document.getElementById("dashboard_date_start");
    const end = document.getElementById("dashboard_date_end");
    if (start) start.value = bounds.start;
    if (end) end.value = bounds.end;
    document.querySelectorAll("[data-dashboard-period]").forEach((button) => {
      button.classList.toggle("active", button.dataset.dashboardPeriod === period);
    });
    render();
  }

  function init() {
    document.querySelectorAll("[data-dashboard-period]").forEach((button) => {
      button.addEventListener("click", () => setPeriod(button.dataset.dashboardPeriod || "month"));
    });
    ["dashboard_date_start", "dashboard_date_end"].forEach((id) => {
      document.getElementById(id)?.addEventListener("change", () => {
        state.period = "custom";
        document.querySelectorAll("[data-dashboard-period]").forEach((button) => button.classList.remove("active"));
        render();
      });
    });
    document.querySelectorAll("[data-dashboard-status]").forEach((button) => {
      button.addEventListener("click", () => {
        const selected = button.dataset.dashboardStatus || "all";
        state.status = state.status === selected && selected !== "all" ? "all" : selected;
        render();
      });
    });
    document.getElementById("dashboard_clear_status")?.addEventListener("click", () => {
      state.status = "all";
      render();
    });
    document.querySelectorAll("[data-open-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.dataset.openTab;
        document.querySelector(`.topbar .tab-btn[data-tab="${target}"]`)?.click();
      });
    });
    setPeriod("month");
  }

  window.renderSuprimentosDashboard = render;
  document.addEventListener("DOMContentLoaded", init);
})();
