const state = { range: "today", data: null };

const formatNumber = (value) => value == null ? "暂无" : new Intl.NumberFormat("zh-CN").format(value);
const formatGrowth = (value) => value == null ? "暂无" : `${value > 0 ? "+" : ""}${formatNumber(value)}`;
const formatRate = (value) => value == null ? "暂无" : `${(value * 100).toFixed(2)}%`;

function pickPoints(points, range) {
  if (!points.length) return [];
  if (range === "today") return points.slice(-1);
  if (range === "7d") return points.slice(-7);
  const month = points.at(-1).date.slice(0, 7);
  return points.filter((point) => point.date.startsWith(month));
}

function sum(points, key) {
  const values = points.map((point) => point[key]).filter((value) => value != null);
  return values.length ? values.reduce((a, b) => a + b, 0) : null;
}

function chartMetric(entity) {
  return entity.group === "Discord 社区" ? "activeMembers" : "views";
}

function drawChart(svg, points, color, metric, label) {
  const values = points.map((point) => point[metric]).filter((value) => value != null);
  if (!values.length) {
    svg.innerHTML = `<text x="320" y="90" text-anchor="middle" class="axis-label">暂无可绘制趋势数据</text>`;
    return;
  }
  const width = 640, height = 184, left = 12, right = 12, top = 14, bottom = 28;
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || Math.max(max * .1, 1);
  const visible = points.filter((point) => point[metric] != null);
  const coords = visible.map((point, index) => {
    const x = left + (visible.length === 1 ? (width - left - right) / 2 : index * (width - left - right) / (visible.length - 1));
    const y = top + (max - point[metric]) * (height - top - bottom) / span;
    return { x, y, point };
  });
  const line = coords.map(({x,y}, i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords.at(-1).x},${height-bottom} L${coords[0].x},${height-bottom} Z`;
  const grids = [top, (top + height - bottom) / 2, height - bottom].map((y) => `<line class="gridline" x1="${left}" y1="${y}" x2="${width-right}" y2="${y}"/>`).join("");
  const dots = coords.map(({x,y,point}) => `<circle class="dot" cx="${x}" cy="${y}" r="4"><title>${point.date} · ${label} ${formatNumber(point[metric])}</title></circle>`).join("");
  const dateLabels = [coords[0], coords.at(-1)].map(({x,point}) => `<text class="axis-label" x="${x}" y="${height-5}" text-anchor="middle">${point.date.slice(5)}</text>`).join("");
  svg.style.setProperty("--color", color);
  svg.innerHTML = `${grids}<path class="area" d="${area}"/><path class="line" d="${line}"/>${dots}${dateLabels}`;
}

function entityMetrics(entity, points) {
  const latest = points.at(-1) || {};
  const isDiscord = entity.group === "Discord 社区";
  const rangeText = state.range === "today" ? "今日" : state.range === "7d" ? "近 7 天" : "本月";
  const metrics = [
    [entity.audience_label, formatNumber(latest.audience)],
    ["净增长", formatGrowth(sum(points, "netGrowth")), sum(points, "netGrowth")],
  ];
  if (isDiscord) {
    metrics.push(["活跃成员", formatNumber(latest.activeMembers)]);
    metrics.push(["活跃率", formatRate(latest.activeRate)]);
  } else {
    metrics.push([`${rangeText}新增浏览`, formatNumber(sum(points, "views"))]);
    metrics.push([`${rangeText}新增互动`, formatNumber(sum(points, "interactions"))]);
    metrics.push(["本月浏览量", formatNumber(latest.monthViews)]);
    metrics.push(["本月互动量", formatNumber(latest.monthInteractions)]);
  }
  return metrics;
}

function render() {
  const root = document.querySelector("#dashboard");
  const entities = state.data.entities;
  const groups = [...new Set(entities.map((entity) => entity.group))];
  root.innerHTML = "";
  groups.forEach((group) => {
    const groupEntities = entities.filter((entity) => entity.group === group);
    const section = document.createElement("section");
    section.className = "group";
    section.style.setProperty("--group-color", groupEntities[0].color);
    section.innerHTML = `<h2 class="group-title">${group}</h2><div class="entity-grid"></div>`;
    const grid = section.querySelector(".entity-grid");
    groupEntities.forEach((entity) => {
      const node = document.querySelector("#entity-template").content.cloneNode(true);
      const card = node.querySelector(".entity-card");
      const points = pickPoints(entity.points, state.range);
      const latest = points.at(-1) || entity.points.at(-1);
      card.style.setProperty("--color", entity.color);
      node.querySelector(".entity-dot").style.background = entity.color;
      node.querySelector(".entity-type").textContent = entity.group;
      node.querySelector(".entity-name").textContent = entity.label;
      node.querySelector(".latest-date").textContent = latest ? `最新：${latest.date}` : "暂无数据";
      node.querySelector(".metric-grid").innerHTML = entityMetrics(entity, points).map(([name, value, raw]) => `<div class="metric"><p class="metric-label">${name}</p><p class="metric-value ${raw > 0 ? "positive" : raw < 0 ? "negative" : ""}">${value}</p></div>`).join("");
      const metric = chartMetric(entity);
      const chartLabel = metric === "activeMembers" ? "活跃成员" : "新增浏览";
      node.querySelector(".chart-title").textContent = `${chartLabel}趋势`;
      node.querySelector(".chart-note").textContent = state.range === "today" ? "今日快照" : `${points.length} 个数据点`;
      drawChart(node.querySelector(".trend-chart"), points, entity.color, metric, chartLabel);
      grid.appendChild(node);
    });
    root.appendChild(section);
  });
}

async function start() {
  const response = await fetch("data/metrics.json", { cache: "no-store" });
  if (!response.ok) throw new Error("数据文件尚未导出");
  state.data = await response.json();
  const latest = state.data.entities.flatMap((entity) => entity.points).map((point) => point.date).sort().at(-1);
  document.querySelector("#updated-at").textContent = `数据截至 ${latest || "暂无"} · 每日北京时间 09:40 自动采集`;
  render();
}

document.querySelectorAll(".range-tab").forEach((button) => button.addEventListener("click", () => {
  state.range = button.dataset.range;
  document.querySelectorAll(".range-tab").forEach((item) => item.classList.toggle("active", item === button));
  render();
}));

start().catch((error) => document.querySelector("#dashboard").innerHTML = `<p class="empty">仪表盘暂不可用：${error.message}</p>`);
