#!/usr/bin/env python3
"""Step-by-step connectivity diagnostic."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    print("=" * 50)
    print("Tipsy Crawler 网络诊断")
    print("=" * 50)

    # Step 1: Sync httpx
    print("\n[1] 同步 httpx 测试...")
    import httpx
    try:
        r = httpx.get("https://api.deepseek.com", timeout=15)
        print(f"    DeepSeek (sync): {r.status_code} OK")
    except Exception as e:
        print(f"    DeepSeek (sync): FAILED - {type(e).__name__}: {e}")

    # Step 2: Async httpx
    print("\n[2] 异步 httpx 测试...")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.deepseek.com")
            print(f"    DeepSeek (async): {r.status_code} OK")
    except Exception as e:
        print(f"    DeepSeek (async): FAILED - {type(e).__name__}: {e}")

    # Step 3: Async httpx POST (like the actual API call)
    print("\n[3] 异步 httpx POST 测试...")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]},
            )
            print(f"    DeepSeek POST: {r.status_code} (401=正常,说明连通)")
    except Exception as e:
        print(f"    DeepSeek POST: FAILED - {type(e).__name__}: {e}")

    # Step 4: Playwright browser
    print("\n[4] Playwright 浏览器测试...")
    from playwright.async_api import async_playwright
    try:
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(headless=True)
            print("    Chromium 启动: OK")
        except Exception:
            chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            browser = await pw.chromium.launch(headless=True, executable_path=str(chrome))
            print("    系统 Chrome 启动: OK")

        page = await browser.new_page()
        try:
            await page.goto("https://tipsy.chat", wait_until="domcontentloaded", timeout=30000)
            title = await page.title()
            print(f"    tipsy.chat 访问: OK (title: {title[:50]})")
        except Exception as e:
            print(f"    tipsy.chat 访问: FAILED - {type(e).__name__}: {e}")
        finally:
            await page.close()
            await browser.close()
            await pw.stop()
    except Exception as e:
        print(f"    Playwright: FAILED - {type(e).__name__}: {e}")

    # Step 5: MuleRouter
    print("\n[5] MuleRouter 测试...")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.mulerouter.ai")
            print(f"    MuleRouter: {r.status_code} OK")
    except Exception as e:
        print(f"    MuleRouter: FAILED - {type(e).__name__}: {e}")

    print("\n" + "=" * 50)
    print("诊断完成")


if __name__ == "__main__":
    asyncio.run(main())
