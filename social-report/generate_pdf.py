from __future__ import annotations

from datetime import datetime
from pathlib import Path

import gspread
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from discord_test import load_env


FONT_REGULAR = "MicrosoftYaHei"
FONT_BOLD = "MicrosoftYaHeiBold"
PLATFORMS = ("Facebook", "Discord", "X")
PLATFORM_COLORS = {
    "Facebook": HexColor("#1877F2"),
    "Discord": HexColor("#5865F2"),
    "X": HexColor("#111827"),
}


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, r"C:\Windows\Fonts\msyh.ttc"))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, r"C:\Windows\Fonts\msyhbd.ttc"))


def as_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except ValueError:
        return None


def as_float(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_integer(value) -> str:
    parsed = as_int(value)
    return "暂无" if parsed is None else f"{parsed:,}"


def format_growth(value) -> str:
    parsed = as_int(value)
    if parsed is None:
        return "暂无基准"
    return f"{parsed:+,}"


def format_rate(value) -> str:
    parsed = as_float(value)
    return "暂无" if parsed is None else f"{parsed:.2%}"


def latest_metrics(base_dir: Path) -> tuple[str, dict[str, dict]]:
    env = load_env(base_dir / ".env")
    credentials_path = (base_dir / env.get("GOOGLE_CREDENTIALS_FILE", "")).resolve()
    sheets = gspread.service_account(filename=str(credentials_path))
    worksheet = sheets.open_by_key(env["GOOGLE_SHEET_ID"]).worksheet("daily_metrics")
    records = worksheet.get_all_records()
    if not records:
        raise RuntimeError("daily_metrics does not contain report data")

    report_date = max(str(row.get("date", "")) for row in records)
    rows = {
        str(row.get("platform")): row
        for row in records
        if str(row.get("date", "")) == report_date
    }
    return report_date, rows


def draw_metric(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    label: str,
    value: str,
    value_color=HexColor("#16233A"),
) -> None:
    pdf.setFillColor(HexColor("#667085"))
    pdf.setFont(FONT_REGULAR, 9)
    pdf.drawString(x, y, label)
    pdf.setFillColor(value_color)
    pdf.setFont(FONT_BOLD, 17 if len(value) < 9 else 13)
    pdf.drawString(x, y - 22, value)


def draw_platform_card(
    pdf: canvas.Canvas,
    platform: str,
    row: dict,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    color = PLATFORM_COLORS[platform]
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.roundRect(x, y, width, height, 12, fill=1, stroke=0)
    pdf.setFillColor(color)
    pdf.roundRect(x, y + height - 42, width, 42, 12, fill=1, stroke=0)
    pdf.rect(x, y + height - 42, width, 12, fill=1, stroke=0)

    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setFont(FONT_BOLD, 15)
    pdf.drawString(x + 16, y + height - 27, platform)
    pdf.setFont(FONT_REGULAR, 9)
    region = str(row.get("region") or "-")
    pdf.drawRightString(x + width - 16, y + height - 26, region)

    if platform == "Discord":
        metrics = [
            ("成员总数", format_integer(row.get("followers_total"))),
            ("净增长", format_growth(row.get("net_growth"))),
            ("活跃成员", format_integer(row.get("active_members"))),
            ("活跃率", format_rate(row.get("active_rate"))),
        ]
    else:
        metrics = [
            ("关注者总数", format_integer(row.get("followers_total"))),
            ("净增长", format_growth(row.get("net_growth"))),
            ("浏览量", format_integer(row.get("impressions"))),
            ("互动量", format_integer(row.get("interactions"))),
            ("本月总浏览量", format_integer(row.get("month_views"))),
            ("本月互动量", format_integer(row.get("month_interactions"))),
        ]

    col_width = (width - 32) / 2
    positions = [
        (x + 16, y + height - 68),
        (x + 16 + col_width, y + height - 68),
        (x + 16, y + height - 116),
        (x + 16 + col_width, y + height - 116),
        (x + 16, y + height - 164),
        (x + 16 + col_width, y + height - 164),
    ]
    for (label, value), (metric_x, metric_y) in zip(metrics, positions):
        value_color = HexColor("#16A34A") if label == "净增长" and value.startswith("+") else HexColor("#16233A")
        draw_metric(pdf, metric_x, metric_y, label, value, value_color)


def draw_audience_chart(
    pdf: canvas.Canvas,
    rows: dict[str, dict],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.roundRect(x, y, width, height, 12, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#16233A"))
    pdf.setFont(FONT_BOLD, 13)
    pdf.drawString(x + 18, y + height - 28, "受众规模对比")
    pdf.setFillColor(HexColor("#667085"))
    pdf.setFont(FONT_REGULAR, 8)
    pdf.drawRightString(x + width - 18, y + height - 27, "关注者 / 成员")

    values = {platform: as_int(rows.get(platform, {}).get("followers_total")) or 0 for platform in PLATFORMS}
    max_value = max(values.values()) or 1
    chart_x = x + 90
    chart_width = width - 180
    first_y = y + height - 68

    for index, platform in enumerate(PLATFORMS):
        bar_y = first_y - index * 42
        value = values[platform]
        pdf.setFillColor(HexColor("#344054"))
        pdf.setFont(FONT_REGULAR, 10)
        pdf.drawString(x + 18, bar_y + 4, platform)
        pdf.setFillColor(HexColor("#E7ECF3"))
        pdf.roundRect(chart_x, bar_y, chart_width, 13, 6, fill=1, stroke=0)
        pdf.setFillColor(PLATFORM_COLORS[platform])
        pdf.roundRect(chart_x, bar_y, chart_width * value / max_value, 13, 6, fill=1, stroke=0)
        pdf.setFillColor(HexColor("#16233A"))
        pdf.setFont(FONT_BOLD, 9)
        pdf.drawRightString(x + width - 18, bar_y + 3, f"{value:,}")


def draw_performance_table(
    pdf: canvas.Canvas,
    rows: dict[str, dict],
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.roundRect(x, y, width, height, 12, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#16233A"))
    pdf.setFont(FONT_BOLD, 13)
    pdf.drawString(x + 18, y + height - 28, "当日与本月表现")

    columns = [x + 18, x + 92, x + 198]
    header_y = y + height - 57
    pdf.setFillColor(HexColor("#667085"))
    pdf.setFont(FONT_REGULAR, 9)
    for column_x, label in zip(columns, ("平台", "当日", "本月累计")):
        pdf.drawString(column_x, header_y, label)

    table_rows = [
        (
            "Facebook",
            (f"浏览 {format_integer(rows.get('Facebook', {}).get('impressions'))}", f"互动 {format_integer(rows.get('Facebook', {}).get('interactions'))}"),
            (f"浏览 {format_integer(rows.get('Facebook', {}).get('month_views'))}", f"互动 {format_integer(rows.get('Facebook', {}).get('month_interactions'))}"),
        ),
        (
            "X",
            (f"浏览 {format_integer(rows.get('X', {}).get('impressions'))}", f"互动 {format_integer(rows.get('X', {}).get('interactions'))}"),
            (f"浏览 {format_integer(rows.get('X', {}).get('month_views'))}", f"互动 {format_integer(rows.get('X', {}).get('month_interactions'))}"),
        ),
        (
            "Discord",
            (f"活跃 {format_integer(rows.get('Discord', {}).get('active_members'))}", f"活跃率 {format_rate(rows.get('Discord', {}).get('active_rate'))}"),
            ("不适用", ""),
        ),
    ]
    for index, values in enumerate(table_rows):
        row_y = header_y - 35 - index * 46
        pdf.setStrokeColor(HexColor("#E7ECF3"))
        pdf.line(x + 18, row_y + 24, x + width - 18, row_y + 24)
        pdf.setFont(FONT_BOLD, 9)
        pdf.setFillColor(PLATFORM_COLORS[values[0]])
        pdf.drawString(columns[0], row_y + 2, values[0])
        pdf.setFont(FONT_REGULAR, 9)
        pdf.setFillColor(HexColor("#344054"))
        pdf.drawString(columns[1], row_y + 8, values[1][0])
        pdf.drawString(columns[1], row_y - 6, values[1][1])
        pdf.drawString(columns[2], row_y + 8, values[2][0])
        if values[2][1]:
            pdf.drawString(columns[2], row_y - 6, values[2][1])


def generate_pdf(base_dir: Path) -> Path:
    register_fonts()
    report_date, rows = latest_metrics(base_dir)
    output_dir = base_dir / "output" / "pdf"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"social-media-daily-report-{report_date}.pdf"
    try:
        with output_path.open("ab"):
            pass
    except PermissionError:
        output_path = output_dir / (
            f"social-media-daily-report-{report_date}-updated-"
            f"{datetime.now().strftime('%H%M%S')}.pdf"
        )

    page_width, page_height = landscape(A4)
    pdf = canvas.Canvas(str(output_path), pagesize=(page_width, page_height))
    pdf.setTitle(f"Social Media Daily Report {report_date}")

    pdf.setFillColor(HexColor("#F4F7FB"))
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)

    margin = 32
    pdf.setFillColor(HexColor("#16233A"))
    pdf.setFont(FONT_BOLD, 23)
    pdf.drawString(margin, page_height - 48, "社交媒体运营日报")
    pdf.setFont(FONT_REGULAR, 10)
    pdf.setFillColor(HexColor("#667085"))
    pdf.drawString(margin, page_height - 67, f"数据日期：{report_date}  |  每日北京时间 09:40 自动生成")
    pdf.drawRightString(
        page_width - margin,
        page_height - 48,
        f"生成时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')}",
    )

    gap = 14
    card_width = (page_width - margin * 2 - gap * 2) / 3
    card_y = 318
    card_height = 190
    for index, platform in enumerate(PLATFORMS):
        draw_platform_card(
            pdf,
            platform,
            rows.get(platform, {}),
            margin + index * (card_width + gap),
            card_y,
            card_width,
            card_height,
        )

    lower_y = 76
    lower_height = 220
    left_width = 450
    draw_audience_chart(pdf, rows, margin, lower_y, left_width, lower_height)
    draw_performance_table(
        pdf,
        rows,
        margin + left_width + gap,
        lower_y,
        page_width - margin * 2 - left_width - gap,
        lower_height,
    )

    statuses = [str(rows.get(platform, {}).get("status") or "missing") for platform in PLATFORMS]
    overall_status = "数据完整" if all(status == "success" for status in statuses) else "存在缺失数据"
    pdf.setFillColor(HexColor("#667085"))
    pdf.setFont(FONT_REGULAR, 8)
    pdf.drawString(margin, 45, "说明：暂无基准表示尚未有前一日快照；0 表示已确认当日为零。数据来源：Google Sheets。")
    pdf.drawRightString(page_width - margin, 45, f"状态：{overall_status}")
    pdf.setStrokeColor(HexColor("#D7DEE8"))
    pdf.line(margin, 61, page_width - margin, 61)

    pdf.showPage()
    pdf.save()
    return output_path


def main() -> None:
    output_path = generate_pdf(Path(__file__).resolve().parent)
    print(f"PDF_PATH={output_path}")


if __name__ == "__main__":
    main()
