const state = { range: "today", data: null };
const nf = new Intl.NumberFormat("zh-CN");
const formatNumber = (value) => value == null ? "暂无" : nf.format(value);
const formatGrowth = (value) => value == null ? "暂无" : `${value > 0 ? "+" : ""}${formatNumber(value)}`;
const formatRate = (value) => value == null ? "暂无" : `${(value * 100).toFixed(2)}%`;
const rangeLabel = () => ({ today: "今日", "7d": "近 7 天", month: "本月" }[state.range]);
const escapeHtml = (text) => String(text).replace(/[&<>"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]));

function pickPoints(points, range) {
  if (!points.length) return [];
  if (range === "today") return points.slice(-1);
  const latest = new Date(`${points.at(-1).date}T00:00:00`);
  if (range === "7d") {
    const start = new Date(latest); start.setDate(start.getDate() - 6);
    return points.filter((point) => new Date(`${point.date}T00:00:00`) >= start);
  }
  const monthStart = new Date(latest.getFullYear(), latest.getMonth(), 1);
  return points.filter((point) => new Date(`${point.date}T00:00:00`) >= monthStart);
}

function chartPoints(entity, points) {
  return state.range === "today" ? pickPoints(entity.points, "7d") : points;
}

function sum(points, key) {
  const values = points.map((point) => point[key]).filter((value) => value != null);
  return values.length ? values.reduce((a, b) => a + b, 0) : null;
}

function entityMetrics(entity, points) {
  const latest = points.at(-1) || {};
  const isDiscord = entity.group === "Discord 社区";
  const label = rangeLabel();
  const metrics = [[entity.audience_label, formatNumber(latest.audience)], ["净增长", formatGrowth(sum(points, "netGrowth")), sum(points, "netGrowth")]];
  if (isDiscord) {
    metrics.push(["活跃成员", formatNumber(latest.activeMembers)]);
    metrics.push(["活跃率", formatRate(latest.activeRate)]);
  } else {
    metrics.push([`${label}新增浏览`, formatNumber(sum(points, "views"))]);
    metrics.push([`${label}新增互动`, formatNumber(sum(points, "interactions"))]);
    metrics.push(["本月浏览量", formatNumber(latest.monthViews)]);
    metrics.push(["本月互动量", formatNumber(latest.monthInteractions)]);
  }
  return metrics;
}

function chartConfigs(entity) {
  if (entity.group === "Discord 社区") {
    return [
      { title: "成员规模与净增长", left: { key: "audience", label: "成员总数", color: entity.color, kind: "line" }, right: { key: "netGrowth", label: "净增长", color: "#F79009", kind: "bar" } },
      { title: "社区活跃趋势", left: { key: "activeMembers", label: "活跃成员", color: entity.color, kind: "line" }, right: { key: "activeRate", label: "活跃率", color: "#7C3AED", format: formatRate, kind: "bar" } },
    ];
  }
  return [
    { title: "浏览量趋势", left: { key: "monthViews", label: "本月浏览量", color: entity.color, kind: "line" }, right: { key: "views", label: "当日新增浏览", color: "#F79009", kind: "bar" } },
    { title: "粉丝规模与净增长", left: { key: "audience", label: entity.audience_label, color: entity.color, kind: "line" }, right: { key: "netGrowth", label: "净增长粉丝", color: "#7C3AED", kind: "bar" } },
  ];
}

function axisScale(values, includeZero = false) {
  let low = Math.min(...values), high = Math.max(...values);
  if (includeZero) { low = Math.min(0, low); high = Math.max(0, high); }
  const span = high - low || Math.max(Math.abs(high), 1);
  const pad = span * 0.12;
  return { min: includeZero ? Math.min(0, low - pad) : low - pad, max: high + pad };
}

function drawDualChart(wrapper, points, config) {
  const width = 720, height = 270, left = 60, right = 62, top = 24, bottom = 86;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const leftValues = points.map((point) => point[config.left.key]).filter((value) => value != null);
  const rightValues = points.map((point) => point[config.right.key]).filter((value) => value != null);
  const chartId = `chart-${Math.random().toString(36).slice(2, 9)}`;
  const tooltip = document.createElement("div");
  tooltip.className = "chart-tooltip";
  tooltip.hidden = true;
  const chart = document.createElement("section");
  chart.className = "chart-wrap";
  chart.innerHTML = `<div class="chart-title-row"><div><h4 class="chart-title">${config.title}</h4><p class="chart-legend"><span style="--legend-color:${config.left.color}">${config.left.label}</span><span style="--legend-color:${config.right.color}">${config.right.label}</span></p></div><span class="chart-note">${state.range === "today" ? "近 7 日数据" : `${points.length} 个数据点`}</span></div><div class="chart-canvas"><svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${config.title}，横轴为日期，左右纵轴分别为 ${config.left.label} 与 ${config.right.label}"></svg></div>`;
  chart.querySelector(".chart-canvas").appendChild(tooltip);
  wrapper.appendChild(chart);
  const svg = chart.querySelector("svg");
  if (!points.length || (!leftValues.length && !rightValues.length)) {
    svg.innerHTML = `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" class="axis-label">暂无可绘制趋势数据</text>`;
    return;
  }
  const leftScale = axisScale(leftValues.length ? leftValues : [0]);
  const rightScale = axisScale(rightValues.length ? rightValues : [0], config.right.kind === "bar");
  const xInset = Math.min(28, plotWidth / Math.max(points.length + 1, 2));
  const x = (index) => points.length === 1
    ? left + plotWidth / 2
    : left + xInset + index * (plotWidth - xInset * 2) / (points.length - 1);
  const y = (value, scale) => top + (scale.max - value) * plotHeight / (scale.max - scale.min || 1);
  const series = [config.left, config.right].map((seriesConfig, seriesIndex) => ({ ...seriesConfig, scale: seriesIndex ? rightScale : leftScale }));
  const horizontalGrid = [0, .25, .5, .75, 1].map((ratio) => {
    const position = top + plotHeight * ratio;
    const lv = leftScale.max - (leftScale.max - leftScale.min) * ratio;
    const rv = rightScale.max - (rightScale.max - rightScale.min) * ratio;
    return `<line class="gridline" x1="${left}" y1="${position}" x2="${width-right}" y2="${position}"/><text class="axis-label axis-left" x="${left-9}" y="${position+4}" text-anchor="end">${formatNumber(Math.round(lv))}</text><text class="axis-label axis-right" x="${width-right+9}" y="${position+4}">${series[1].format ? series[1].format(rv) : formatNumber(Math.round(rv))}</text>`;
  }).join("");
  const xAxis = `<line class="axis-line" x1="${left}" y1="${top+plotHeight}" x2="${width-right}" y2="${top+plotHeight}"/><line class="axis-line" x1="${left}" y1="${top}" x2="${left}" y2="${top+plotHeight}"/><line class="axis-line" x1="${width-right}" y1="${top}" x2="${width-right}" y2="${top+plotHeight}"/>`;
  const dateLabels = points.map((point, index) => `<g transform="translate(${x(index)},${top+plotHeight+15}) rotate(-42)"><text class="axis-label axis-date" text-anchor="end">${point.date}</text></g>`).join("");
  const lines = series.filter((seriesConfig) => seriesConfig.kind !== "bar").map((seriesConfig) => {
    const coords = points.map((point, index) => point[seriesConfig.key] == null ? null : { x: x(index), y: y(point[seriesConfig.key], seriesConfig.scale) });
    const segments = []; let path = "";
    coords.forEach((coord) => { if (!coord) { if (path) segments.push(path); path = ""; } else path += `${path ? " L" : "M"}${coord.x.toFixed(1)},${coord.y.toFixed(1)}`; }); if (path) segments.push(path);
    return segments.map((segment) => `<path class="line" d="${segment}" stroke="${seriesConfig.color}"/>`).join("");
  }).join("");
  const bars = points.map((point, index) => {
    if (point[config.right.key] == null) return "";
    const valueY = y(point[config.right.key], rightScale); const baselineY = top + plotHeight; const barWidth = Math.min(32, plotWidth / Math.max(points.length * 1.8, 2));
    const tooltipText = `${point.date}\n${config.left.label}  ${config.left.format ? config.left.format(point[config.left.key]) : formatNumber(point[config.left.key])}\n${config.right.label}  ${config.right.format ? config.right.format(point[config.right.key]) : formatNumber(point[config.right.key])}`;
    return `<rect class="bar interactive-bar" data-chart="${chartId}" data-tip="${escapeHtml(tooltipText)}" tabindex="0" role="img" aria-label="${point.date}，${config.left.label} ${formatNumber(point[config.left.key])}，${config.right.label} ${formatNumber(point[config.right.key])}" x="${x(index)-barWidth/2}" y="${Math.min(valueY, baselineY)}" width="${barWidth}" height="${Math.max(1, baselineY-valueY)}" fill="${config.right.color}"/>`;
  }).join("");
  const dots = points.flatMap((point, index) => series.filter((seriesConfig) => seriesConfig.kind !== "bar" && point[seriesConfig.key] != null).map((seriesConfig) => {
    const leftText = config.left.format ? config.left.format(point[config.left.key]) : formatNumber(point[config.left.key]);
    const rightText = config.right.format ? config.right.format(point[config.right.key]) : formatNumber(point[config.right.key]);
    const text = `${point.date}\n${config.left.label}  ${leftText}\n${config.right.label}  ${rightText}`;
    return `<circle class="dot interactive-dot" data-chart="${chartId}" data-tip="${escapeHtml(text)}" tabindex="0" role="img" aria-label="${point.date}，${config.left.label} ${leftText}，${config.right.label} ${rightText}" cx="${x(index)}" cy="${y(point[seriesConfig.key], seriesConfig.scale)}" r="4.5" stroke="${seriesConfig.color}"/>`;
  })).join("");
  svg.innerHTML = `${horizontalGrid}${xAxis}${bars}${lines}${dots}${dateLabels}<text class="axis-title" x="${left}" y="14" fill="${config.left.color}">${config.left.label}</text><text class="axis-title" x="${width-right}" y="14" text-anchor="end" fill="${config.right.color}">${config.right.label}</text>`;
  chart.querySelectorAll(`[data-chart="${chartId}"]`).forEach((dot) => {
    const showTip = (event) => { tooltip.textContent = dot.dataset.tip; tooltip.hidden = false; const bounds = chart.querySelector(".chart-canvas").getBoundingClientRect(); const pointerX = event?.clientX || bounds.left + bounds.width / 2; tooltip.style.left = `${Math.max(8, Math.min(bounds.width - 156, pointerX - bounds.left + 10))}px`; tooltip.style.top = "18px"; };
    dot.addEventListener("mouseenter", showTip); dot.addEventListener("focus", showTip);
    dot.addEventListener("mouseleave", () => { tooltip.hidden = true; }); dot.addEventListener("blur", () => { tooltip.hidden = true; });
  });
}

function renderOverview() {
  const latestDates = state.data.entities.flatMap((entity) => entity.points).map((point) => point.date).sort();
  const latest = latestDates.at(-1) || "暂无";
  const success = state.data.entities.filter((entity) => entity.points.at(-1)?.status?.startsWith("success")).length;
  const icons = { accounts: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.8 20a5.2 5.2 0 0 1 10.4 0M16 5.5a3 3 0 0 1 0 5.8M18 20a5.2 5.2 0 0 0-2.8-4.6"/></svg>', date: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/></svg>', status: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 2.6 2.6L16.5 9"/></svg>' };
  document.querySelector("#overview").innerHTML = [["监测账号", state.data.entities.length, "accounts"], ["最新数据", latest, "date"], ["采集状态", `${success}/${state.data.entities.length} 正常`, "status"]].map(([label, value, icon]) => `<div class="overview-item"><div><p class="overview-label">${label}</p><p class="overview-value">${value}</p></div><span class="overview-icon">${icons[icon]}</span></div>`).join("");
}

function renderNavigation() {
  document.querySelector("#section-nav").innerHTML = `<span class="nav-label">快速定位</span>${state.data.entities.map((entity) => `<a href="#${entity.id}" style="--nav-color:${entity.color}"><span></span>${entity.label}</a>`).join("")}`;
}

function render() {
  renderOverview(); renderNavigation();
  const root = document.querySelector("#dashboard");
  const groups = [...new Set(state.data.entities.map((entity) => entity.group))]; root.innerHTML = "";
  groups.forEach((group) => {
    const entities = state.data.entities.filter((entity) => entity.group === group);
    const section = document.createElement("section"); section.className = "group"; section.style.setProperty("--group-color", entities[0].color);
    section.innerHTML = `<div class="group-heading"><h2 class="group-title">${group}</h2><p class="group-count">${entities.length} 个账号</p></div><div class="entity-grid"></div>`;
    const grid = section.querySelector(".entity-grid");
    entities.forEach((entity) => {
      const node = document.querySelector("#entity-template").content.cloneNode(true); const card = node.querySelector(".entity-card");
      const points = pickPoints(entity.points, state.range); const latest = points.at(-1) || entity.points.at(-1);
      card.id = entity.id; card.style.setProperty("--color", entity.color); node.querySelector(".entity-dot").style.background = entity.color;
      node.querySelector(".entity-type").textContent = entity.group; node.querySelector(".entity-name").textContent = entity.label; node.querySelector(".latest-date").textContent = latest ? `更新于 ${latest.date}` : "暂无数据";
      node.querySelector(".metric-grid").innerHTML = entityMetrics(entity, points).map(([name, value, raw]) => `<div class="metric"><p class="metric-label">${name}</p><p class="metric-value ${raw > 0 ? "positive" : raw < 0 ? "negative" : ""}">${value}</p></div>`).join("");
      const charts = node.querySelector(".chart-list"); chartConfigs(entity).forEach((config) => drawDualChart(charts, chartPoints(entity, points), config)); grid.appendChild(node);
    }); root.appendChild(section);
  });
}

async function start() {
  const response = await fetch("data/metrics.json", { cache: "no-store" }); if (!response.ok) throw new Error("数据文件尚未导出");
  state.data = await response.json(); const latest = state.data.entities.flatMap((entity) => entity.points).map((point) => point.date).sort().at(-1);
  document.querySelector("#updated-at").textContent = `数据截至 ${latest || "暂无"} · 北京时间每日 09:40 自动采集`; render();
}
document.querySelectorAll(".range-tab").forEach((button) => button.addEventListener("click", () => { state.range = button.dataset.range; document.querySelectorAll(".range-tab").forEach((item) => { const active = item === button; item.classList.toggle("active", active); item.setAttribute("aria-selected", String(active)); }); render(); }));
start().catch((error) => document.querySelector("#dashboard").innerHTML = `<p class="empty">仪表盘暂不可用：${error.message}</p>`);
