from __future__ import annotations

from datetime import datetime
from pathlib import Path

import gspread
import pypdfium2 as pdfium
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from discord_test import load_env


FONT_REGULAR = "MicrosoftYaHei"
FONT_BOLD = "MicrosoftYaHeiBold"
ENTITY_KEYS = ("Facebook", "Discord:LATAM", "Discord:Global", "X")
ENTITY_LABELS = {
    "Facebook": "Facebook",
    "Discord:LATAM": "Discord LATAM",
    "Discord:Global": "Discord Global",
    "X": "X",
}
ENTITY_COLORS = {
    "Facebook": HexColor("#1877F2"),
    "Discord:LATAM": HexColor("#5865F2"),
    "Discord:Global": HexColor("#7C3AED"),
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
    rows = {}
    for row in records:
        if str(row.get("date", "")) != report_date:
            continue
        platform = str(row.get("platform"))
        region = str(row.get("region"))
        key = f"Discord:{region}" if platform == "Discord" else platform
        rows[key] = row
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
    entity_key: str,
    row: dict,
    x: float,
    y: float,
    width: float,
    height: float,
) -> None:
    platform = entity_key.split(":", 1)[0]
    color = ENTITY_COLORS[entity_key]
    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.roundRect(x, y, width, height, 12, fill=1, stroke=0)
    pdf.setFillColor(color)
    pdf.roundRect(x, y + height - 42, width, 42, 12, fill=1, stroke=0)
    pdf.rect(x, y + height - 42, width, 12, fill=1, stroke=0)

    pdf.setFillColor(HexColor("#FFFFFF"))
    pdf.setFont(FONT_BOLD, 14)
    pdf.drawString(x + 16, y + height - 27, platform)
    pdf.setFont(FONT_REGULAR, 7)
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
            ("新增浏览量", format_integer(row.get("impressions"))),
            ("新增互动量", format_integer(row.get("interactions"))),
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

    values = {
        key: as_int(rows.get(key, {}).get("followers_total")) or 0
        for key in ENTITY_KEYS
    }
    max_value = max(values.values()) or 1
    chart_x = x + 108
    chart_width = width - 198
    first_y = y + height - 61

    for index, entity_key in enumerate(ENTITY_KEYS):
        bar_y = first_y - index * 34
        value = values[entity_key]
        pdf.setFillColor(HexColor("#344054"))
        pdf.setFont(FONT_REGULAR, 10)
        pdf.drawString(x + 18, bar_y + 4, ENTITY_LABELS[entity_key])
        pdf.setFillColor(HexColor("#E7ECF3"))
        pdf.roundRect(chart_x, bar_y, chart_width, 13, 6, fill=1, stroke=0)
        pdf.setFillColor(ENTITY_COLORS[entity_key])
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
    pdf.drawString(x + 18, y + height - 28, "每日新增与本月累计")

    columns = [x + 18, x + width * 0.34, x + width * 0.67]
    header_y = y + height - 57
    pdf.setFillColor(HexColor("#667085"))
    pdf.setFont(FONT_REGULAR, 9)
    for column_x, label in zip(columns, ("平台", "当日新增", "本月累计")):
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
            "Discord:LATAM",
            (f"活跃 {format_integer(rows.get('Discord:LATAM', {}).get('active_members'))}", f"活跃率 {format_rate(rows.get('Discord:LATAM', {}).get('active_rate'))}"),
            ("不适用", ""),
        ),
        (
            "Discord:Global",
            (f"活跃 {format_integer(rows.get('Discord:Global', {}).get('active_members'))}", f"活跃率 {format_rate(rows.get('Discord:Global', {}).get('active_rate'))}"),
            ("不适用", ""),
        ),
    ]
    for index, values in enumerate(table_rows):
        row_y = header_y - 31 - index * 38
        pdf.setStrokeColor(HexColor("#E7ECF3"))
        pdf.line(x + 18, row_y + 24, x + width - 18, row_y + 24)
        pdf.setFont(FONT_BOLD, 9)
        pdf.setFillColor(ENTITY_COLORS[values[0]])
        table_label = ENTITY_LABELS[values[0]].replace("Discord ", "DC ")
        pdf.drawString(columns[0], row_y + 2, table_label)
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
    output_dir = base_dir / "tmp" / "pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"social-media-daily-report-{report_date}-render.pdf"

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

    gap = 10
    card_width = (page_width - margin * 2 - gap * 3) / 4
    card_y = 318
    card_height = 190
    for index, entity_key in enumerate(ENTITY_KEYS):
        draw_platform_card(
            pdf,
            entity_key,
            rows.get(entity_key, {}),
            margin + index * (card_width + gap),
            card_y,
            card_width,
            card_height,
        )

    lower_y = 76
    lower_height = 220
    draw_performance_table(
        pdf,
        rows,
        margin,
        lower_y,
        page_width - margin * 2,
        lower_height,
    )

    statuses = [
        str(rows.get(entity_key, {}).get("status") or "missing")
        for entity_key in ENTITY_KEYS
    ]
    overall_status = "数据完整" if all(status == "success" for status in statuses) else "存在缺失数据"
    pdf.setFillColor(HexColor("#667085"))
    pdf.setFont(FONT_REGULAR, 8)
    pdf.drawString(margin, 45, "说明：日增量 = 当日本月累计快照 - 前一日快照；暂无基准表示无可用前日快照。")
    pdf.drawRightString(page_width - margin, 45, f"状态：{overall_status}")
    pdf.setStrokeColor(HexColor("#D7DEE8"))
    pdf.line(margin, 61, page_width - margin, 61)

    pdf.showPage()
    pdf.save()
    return output_path


def generate_png(pdf_path: Path, base_dir: Path) -> Path:
    report_date = pdf_path.name.split("social-media-daily-report-", 1)[1][:10]
    output_dir = base_dir / "output" / "png"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"social-media-daily-report-{report_date}.png"
    try:
        with output_path.open("ab"):
            pass
    except PermissionError:
        output_path = output_dir / (
            f"social-media-daily-report-{report_date}-updated-"
            f"{datetime.now().strftime('%H%M%S')}.png"
        )

    document = pdfium.PdfDocument(str(pdf_path))
    try:
        image = document[0].render(scale=2.2).to_pil()
        image.save(output_path, format="PNG", optimize=True)
    finally:
        document.close()
    return output_path


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    pdf_path = generate_pdf(base_dir)
    try:
        png_path = generate_png(pdf_path, base_dir)
    finally:
        pdf_path.unlink(missing_ok=True)
    print(f"PNG_PATH={png_path}")


if __name__ == "__main__":
    main()
