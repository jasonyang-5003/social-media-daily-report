# Facebook 自动补漏

每天的 `run_daily.py` 在 Facebook 昨日采集之前执行
`facebook_backfill.py --auto --apply`，随后照常导出并发布仪表盘。

- 检查北京时间今天往前 29 天至前天；昨日由日常采集负责。
- 检查缺失日期，以及粉丝总数、净增长、发布内容数的空字段。
- 只补空字段，保留已有数值和真实的 0，不修改其他平台。
- Metricool 返回空值时保持为空，下次运行再次尝试。
- 不从历史日期页面重建当时的帖子累计浏览量、互动量或每日快照差值。
- 单日读取失败后继续其他日期；失败会在运行日志中提示，昨日采集和网站发布仍会执行。
- 写入前在本地 `logs/facebook-backfill-*.json` 保存原数据和采集结果；该目录不提交 Git。
- 补录完成后回读表格校验。再次运行不会重复新增已有日期。

手动预览：

```powershell
py -3.12 social-report/facebook_backfill.py --auto
```

限定日期预览（加 `--apply` 才写入）：

```powershell
py -3.12 social-report/facebook_backfill.py --start 2026-10-01 --end 2026-10-08
```

免费版可访问范围以 Metricool 页面实际权限为准。超过可访问范围的历史缺口不会自动恢复。
