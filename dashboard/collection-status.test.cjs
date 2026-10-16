const { test } = require('node:test');
const assert = require('node:assert/strict');
const { collectionStatus } = require('./collection-status.js');
const now = new Date('2026-10-12T02:00:00Z');
const point = { date: '2026-10-11', status: 'success', views: 3, interactions: 1 };
const entity = (points = [point]) => ({ id: 'facebook', group: '社媒主页', points });

test('Facebook partial status identifies missing fields and missing delta baseline', () => {
  const result = collectionStatus(entity([{ ...point, status: 'partial_metricool_posts_unavailable',
    views: null, interactions: null, monthViews: 116, monthInteractions: 6,
    publishedCount: null, monthPublished: 1 }]), [], now);
  assert.equal(result.level, 'warning');
  assert.doesNotMatch(result.text, /当日发布内容数/);
  assert.match(result.text, /缺少前一天累计快照/);
  assert.doesNotMatch(result.text, /未返回本月浏览量/);
});
test('healthy zero counts are not considered missing', () => {
  assert.equal(collectionStatus(entity([{ ...point, views: 0, interactions: 0 }]), [], now).level, 'normal');
});
test('stale successful data is named as not updated after scheduled collection', () => {
  const e = entity([{ ...point, date: '2026-10-10' }]);
  assert.match(collectionStatus(e, [], now).text, /未更新/);
  assert.equal(collectionStatus(e, [], new Date('2026-10-12T01:00:00Z')).level, 'normal');
});
test('failed jobs override older successful point, pending jobs show collecting', () => {
  assert.equal(collectionStatus(entity(), [{ entity: 'facebook', date: point.date, state: 'failed' }], now).level, 'warning');
  assert.equal(collectionStatus(entity(), [{ entity: 'facebook', date: point.date, state: 'pending' }], now).level, 'pending');
});
test('old failures and other account jobs do not mislabel a recovered account', () => {
  assert.equal(collectionStatus(entity(), [
    { entity: 'facebook', date: '2026-10-10', state: 'failed' },
    { entity: 'x', date: point.date, state: 'failed' }
  ], now).level, 'normal');
});
test('no points and unknown status are not healthy', () => {
  assert.equal(collectionStatus(entity([]), [], now).level, 'warning');
  assert.equal(collectionStatus(entity([{ ...point, status: 'failed' }]), [], now).level, 'warning');
});
