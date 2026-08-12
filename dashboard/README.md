# 社媒数据仪表盘部署说明

此目录是 Cloudflare Pages 的静态站点根目录。

## Cloudflare Pages 设置

1. 在 Cloudflare Dashboard 中进入 **Workers & Pages**，选择 **Create application** → **Pages** → **Connect to Git**。
2. 选择 GitHub 仓库 `jasonyang-5003/social-media-daily-report`。
3. 使用以下设置：
   - Framework preset：`None`
   - Build command：留空
   - Build output directory：`dashboard`
4. 点击 **Save and Deploy**。

首次部署完成后，Cloudflare 会给出一个 `*.pages.dev` 地址。以后只要 GitHub 的 `main` 分支收到包含 `dashboard/data/metrics.json` 的提交，网站就会自动更新。

## 每日更新

每天 09:40 的本地任务会执行：

1. 所有社媒采集器写入 Google Sheets。
2. `social-report/export_dashboard_data.py` 生成公开的 `dashboard/data/metrics.json`。

要让 Cloudflare 更新，只需要将这个数据文件推送到 GitHub。仪表盘数据文件不包含 API Key、Cookie、服务账号密钥或登录令牌。
