const state = { range: "today", data: null };
const nf = new Intl.NumberFormat("zh-CN");
const formatNumber = (value) => value == null ? "暂无" : nf.format(value);
const formatGrowth = (value) => value == null ? "暂无" : `${value > 0 ? "+" : ""}${formatNumber(value)}`;
const formatRate = (value) => value == null ? "暂无" : `${(value * 100).toFixed(2)}%`;
const rangeLabel = () => ({ today: "今日", "7d": "近 7 天", month: "本月" }[state.range]);

function pickPoints(points, range) {
  if (!points.length) return [];
  if (range === "today") return points.slice(-1);
  if (range === "7d") return points.slice(-7);
  const month = points.at(-1).date.slice(0, 7);
  return points.filter((point) => point.date.startsWith(month));
}
function sum(points, key) { const values = points.map((p) => p[key]).filter((v) => v != null); return values.length ? values.reduce((a,b) => a + b, 0) : null; }
function chartMetric(entity) { return entity.group === "Discord 社区" ? "activeMembers" : "views"; }

function drawChart(svg, points, color, metric, label) {
  const visible = points.filter((p) => p[metric] != null);
  if (!visible.length) { svg.innerHTML = `<text x="320" y="88" text-anchor="middle" class="axis-label">暂无可绘制趋势数据</text>`; return; }
  const width = 640, height = 184, left = 12, right = 12, top = 14, bottom = 28;
  const values = visible.map((p) => p[metric]); const max = Math.max(...values), min = Math.min(...values); const span = max - min || Math.max(max * .1, 1);
  const coords = visible.map((point, index) => ({ point, x: left + (visible.length === 1 ? (width-left-right)/2 : index*(width-left-right)/(visible.length-1)), y: top + (max-point[metric])*(height-top-bottom)/span }));
  const line = coords.map(({x,y}, i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords.at(-1).x},${height-bottom} L${coords[0].x},${height-bottom} Z`;
  const grids = [top, (top + height-bottom)/2, height-bottom].map((y) => `<line class="gridline" x1="${left}" y1="${y}" x2="${width-right}" y2="${y}"/>`).join("");
  const dots = coords.map(({x,y,point}) => `<circle class="dot" cx="${x}" cy="${y}" r="4"><title>${point.date} · ${label} ${formatNumber(point[metric])}</title></circle>`).join("");
  const dateLabels = [coords[0], coords.at(-1)].filter((v,i,a) => i === 0 || v.x !== a[0].x).map(({x,point}) => `<text class="axis-label" x="${x}" y="${height-5}" text-anchor="middle">${point.date.slice(5)}</text>`).join("");
  svg.style.setProperty("--color", color); svg.innerHTML = `${grids}<path class="area" d="${area}"/><path class="line" d="${line}"/>${dots}${dateLabels}`;
}

function entityMetrics(entity, points) {
  const latest = points.at(-1) || {}; const isDiscord = entity.group === "Discord 社区"; const label = rangeLabel();
  const metrics = [[entity.audience_label, formatNumber(latest.audience)], ["净增长", formatGrowth(sum(points, "netGrowth")), sum(points, "netGrowth")]];
  if (isDiscord) { metrics.push(["活跃成员", formatNumber(latest.activeMembers)]); metrics.push(["活跃率", formatRate(latest.activeRate)]); }
  else { metrics.push([`${label}新增浏览`, formatNumber(sum(points, "views"))]); metrics.push([`${label}新增互动`, formatNumber(sum(points, "interactions"))]); metrics.push(["本月浏览量", formatNumber(latest.monthViews)]); metrics.push(["本月互动量", formatNumber(latest.monthInteractions)]); }
  return metrics;
}

function renderOverview() {
  const latestDates = state.data.entities.flatMap((e) => e.points).map((p) => p.date).sort();
  const latest = latestDates.at(-1) || "暂无"; const success = state.data.entities.filter((e) => e.points.at(-1)?.status?.startsWith("success")).length;
  const icons = {
    accounts: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3.8 20a5.2 5.2 0 0 1 10.4 0M16 5.5a3 3 0 0 1 0 5.8M18 20a5.2 5.2 0 0 0-2.8-4.6"/></svg>',
    date: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18M8 14h3M8 17h6"/></svg>',
    status: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8 12 2.6 2.6L16.5 9"/></svg>',
  };
  document.querySelector("#overview").innerHTML = [["监测账号", state.data.entities.length, "accounts"], ["最新数据", latest, "date"], ["采集状态", `${success}/${state.data.entities.length} 正常`, "status"]].map(([label,value,icon]) => `<div class="overview-item"><div><p class="overview-label">${label}</p><p class="overview-value">${value}</p></div><span class="overview-icon">${icons[icon]}</span></div>`).join("");
}

function render() {
  renderOverview(); const root = document.querySelector("#dashboard"); const groups = [...new Set(state.data.entities.map((e) => e.group))]; root.innerHTML = "";
  groups.forEach((group) => { const entities = state.data.entities.filter((e) => e.group === group); const section = document.createElement("section"); section.className = "group"; section.style.setProperty("--group-color", entities[0].color); section.innerHTML = `<div class="group-heading"><h2 class="group-title">${group}</h2><p class="group-count">${entities.length} 个账号</p></div><div class="entity-grid"></div>`; const grid = section.querySelector(".entity-grid");
    entities.forEach((entity) => { const node = document.querySelector("#entity-template").content.cloneNode(true); const card = node.querySelector(".entity-card"); const points = pickPoints(entity.points, state.range); const latest = points.at(-1) || entity.points.at(-1); card.style.setProperty("--color", entity.color); node.querySelector(".entity-dot").style.background = entity.color; node.querySelector(".entity-type").textContent = entity.group; node.querySelector(".entity-name").textContent = entity.label; node.querySelector(".latest-date").textContent = latest ? `更新于 ${latest.date}` : "暂无数据"; node.querySelector(".metric-grid").innerHTML = entityMetrics(entity, points).map(([name,value,raw]) => `<div class="metric"><p class="metric-label">${name}</p><p class="metric-value ${raw > 0 ? "positive" : raw < 0 ? "negative" : ""}">${value}</p></div>`).join(""); const metric = chartMetric(entity); const chartPoints = state.range === "today" ? pickPoints(entity.points, "7d") : points; const chartLabel = metric === "activeMembers" ? "活跃成员" : "新增浏览"; node.querySelector(".chart-title").textContent = `${chartLabel}趋势`; node.querySelector(".chart-note").textContent = state.range === "today" ? "近 7 日走势" : `${chartPoints.length} 个数据点`; drawChart(node.querySelector(".trend-chart"), chartPoints, entity.color, metric, chartLabel); grid.appendChild(node); }); root.appendChild(section); });
}

async function start() { const response = await fetch("data/metrics.json", { cache: "no-store" }); if (!response.ok) throw new Error("数据文件尚未导出"); state.data = await response.json(); const latest = state.data.entities.flatMap((e) => e.points).map((p) => p.date).sort().at(-1); document.querySelector("#updated-at").textContent = `数据截至 ${latest || "暂无"} · 北京时间每日 09:40 自动采集`; render(); }
document.querySelectorAll(".range-tab").forEach((button) => button.addEventListener("click", () => { state.range = button.dataset.range; document.querySelectorAll(".range-tab").forEach((item) => { const active = item === button; item.classList.toggle("active", active); item.setAttribute("aria-selected", String(active)); }); render(); }));
start().catch((error) => document.querySelector("#dashboard").innerHTML = `<p class="empty">仪表盘暂不可用：${error.message}</p>`);
