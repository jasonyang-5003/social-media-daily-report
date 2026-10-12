/* Shared by the browser and the status regression tests. */
function collectionStatus(entity, jobs = [], now = new Date()) {
  const latest = entity.points.at(-1);
  const beijing = new Date(now.getTime() + 8 * 3600000);
  const daysBack = beijing.getUTCHours() * 60 + beijing.getUTCMinutes() < 580 ? 2 : 1;
  beijing.setUTCDate(beijing.getUTCDate() - daysBack);
  const expected = beijing.toISOString().slice(0, 10);
  const activeJobs = jobs.filter(job => job.entity === entity.id &&
    (!latest || job.date >= latest.date));
  if (activeJobs.some(job => job.state === 'failed')) {
    return { level: 'warning', text: '采集失败，请检查该账号的授权或接口状态' };
  }
  if (activeJobs.some(job => ['pending', 'running'].includes(job.state))) {
    return { level: 'pending', text: '正在采集，最新数据尚未齐全' };
  }
  if (!latest) return { level: 'warning', text: '尚无采集数据' };
  const reasons = [];
  if (latest.date < expected) reasons.push(`数据未更新，最近数据为 ${latest.date}`);
  if (latest.status === 'partial_metricool_posts_unavailable') {
    const missing = [['monthViews', '本月浏览量'], ['monthInteractions', '本月互动量'],
      ['publishedCount', '当日发布内容数'], ['monthPublished', '本月发布内容数']]
      .filter(([key]) => latest[key] == null).map(([, label]) => label);
    reasons.push(`Metricool 未返回${missing.length ? missing.join('、') : '完整内容数据'}`);
  } else if (latest.status === 'partial_historical_no_snapshot') {
    reasons.push('仅补回部分历史数据，缺少当日累计快照');
  } else if (!latest.status?.startsWith('success')) {
    reasons.push('采集结果不完整或失败，请检查数据源');
  }
  if (entity.group !== 'Discord 社区' &&
      ((latest.views == null && latest.monthViews != null) ||
       (latest.interactions == null && latest.monthInteractions != null))) {
    const previousDate = new Date(`${latest.date}T00:00:00Z`);
    previousDate.setUTCDate(previousDate.getUTCDate() - 1);
    const previous = entity.points.find(point => point.date === previousDate.toISOString().slice(0, 10));
    if (!previous || previous.date.slice(0, 7) !== latest.date.slice(0, 7) ||
        (latest.views == null && previous.monthViews == null) ||
        (latest.interactions == null && previous.monthInteractions == null)) {
      reasons.push('缺少前一天累计快照，暂无法计算日新增浏览或互动');
    } else {
      reasons.push('日新增浏览或互动尚未生成');
    }
  }
  return reasons.length ? { level: 'warning', text: reasons.join('；') }
    : { level: 'normal', text: '采集正常' };
}
if (typeof module !== 'undefined') module.exports = { collectionStatus };
