from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


METRICOOL_URL = (
    "https://app.metricool.com/evolution/facebookPage"
    "?blogId=6680040&userId=5139837"
)


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    profile_dir = base_dir / ".metricool-browser-profile"

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="msedge",
            headless=False,
            viewport={"width": 1400, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(METRICOOL_URL, wait_until="domcontentloaded", timeout=60_000)

        print("请在打开的 Edge 窗口中登录 Metricool。")
        print("登录成功并看到 Facebook 数据页面后，回到此窗口按 Enter。")
        input()

        page.goto(METRICOOL_URL, wait_until="domcontentloaded", timeout=60_000)
        if "/login" in page.url:
            raise RuntimeError("Metricool 仍处于未登录状态，请重新运行此脚本")

        context.close()
        print("METRICOOL_LOGIN_SAVED=success")


if __name__ == "__main__":
    main()
