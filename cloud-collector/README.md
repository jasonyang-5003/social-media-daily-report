# 云端社媒采集

Cloudflare Workers + D1 保存 Discord LATAM、Discord Global、X US、YouTube Mary。
每天北京时间 09:40 创建一次采集任务；每分钟只推进未完成任务，不每分钟重复采集。
Discord 历史消息按频道分页，X Apify 按 run ID 异步轮询，失败最多重试五次。
X 启动请求若超时不自动重开收费任务，需检查 Apify 后处理。

## 部署

1. `npx wrangler login` 重新授权。
2. `py -3.12 cloud-collector/deploy.py setup` 创建/复用 D1、上传本地凭据至 Workers Secrets、部署、导入历史、启动实测。
3. `py -3.12 cloud-collector/deploy.py status` 检查任务；等待所有任务完成。
4. `py -3.12 cloud-collector/deploy.py activate` 只在四个账号都完成云端实测后切换。
5. `py -3.12 social-report/cloud_sync.py` 同步 Google Sheets，然后正常导出、提交和发布仪表盘代码。

API `/metrics` 仅公开与现有仪表盘相同的汇总指标，不公开成员 ID、消息内容或凭据。
`/admin/*`、`/internal/*` 均需要随机管理令牌。凭据仅在 Workers Secrets 和被 Git 忽略的本地状态文件中保存。
浏览器直接请求云端数据，无需电脑开机或每天 Git 推送。
Facebook 继续使用电脑中的 Metricool 会话。

## 口径与限制

- 所有消息/视频/帖子按北京时间日期分组，昨日日期记录每天早上的人数/累计浏览快照；保留实际采集时间。
- Discord 成员数为 approximate_member_count，与原采集方式一致；不重建缺失的历史人数。
- 人数净增长及内容每日浏览/互动只在连续两天快照存在时计算；跨月不减上月累计。
- Discord 信息统计仍限可读普通频道/公告频道、非机器人消息。删除的消息无法补回。
- X 和 YouTube 只从当前仍存在的内容补历史发布数，不把当前累计浏览倒填到过去。
- X 每日只启动一个 Apify run，最多 1000 条、费用上限 0.005 美元；跨月补漏扩大查询日期但保持费用上限，若数据被截断保持异常。
- 无数据的月份，YouTube 浏览/互动为真实零；X 若日期范围没有帖子且未返回作者，人数留空并报告异常。
- Worker Free 每次 CPU 仅 10ms。已按分页分任务降低用量；是否满足实际 CPU 限制须以线上实测为准，不自动升级付费。
- 每天北京时间 09:10 自动清理超过 35 天的已完成任务及分页临时数据；汇总历史永久保留，不删除指标数据。

## 回退

将被 Git 忽略的 `cloud-collector/local-state.json` 的 enabled 改为 false，电脑恢复原采集。
同时停止 Worker Cron，再清空 dashboard/cloud-config.js 的 URL，避免双重采集/重复 Apify 消耗。
不要删除 D1 数据库，保留云端历史备份。
