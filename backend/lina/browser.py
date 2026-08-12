"""browser.py — BrowserService, her eyes, in the loop.

The browser is the one tool that owns a long-lived resource (a browser
process), so it is a service in the aiomisc loop with a real lifecycle:
``start()`` opens her eyes when the loop comes up, ``stop()`` closes them
cleanly when it comes down. Playwright drives headless Chromium.

If the browser binary is not installed (a dev host without the image's
playwright step), the service stays honest: ``available=False``, a loud log
line, and every browser tool returns "her eyes are not open". There is no
fake page and no silent fallback — closed eyes are closed eyes. The page is
hers to keep: one page, her current view; navigate moves it, extract reads
it, screenshot captures it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from aiomisc import Service

log = logging.getLogger("lina.browser")


class BrowserService(Service):
    """Owns the headless browser — her eyes — under aiomisc's lifecycle."""

    def __init__(
        self,
        headless: bool = True,
        timeout: float = 15.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.headless = headless
        self.timeout = timeout
        self.available = False
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self.available = True
        except Exception as exc:  # noqa: BLE001 - unavailable is a state, not a crash
            self.available = False
            log.warning(
                "[browser] her eyes are closed — playwright/chromium unavailable (%s)",
                exc,
            )
        # Publish into the loop's Context — tools resolve her eyes via the
        # context, the same way every other resource is resolved.
        self.context["browser_service"] = self
        log.info("[browser] eyes %s", "open" if self.available else "closed")

    async def _ensure_page(self) -> Any:
        if self._page is None and self._browser is not None:
            self._page = await self._browser.new_page()
        return self._page

    async def navigate(self, url: str) -> str:
        """Move her view to a page and return what it reads."""
        page = await self._ensure_page()
        if page is None:
            raise RuntimeError("browser is not available")
        await page.goto(url, timeout=int(self.timeout * 1000), wait_until="domcontentloaded")
        await page.wait_for_timeout(400)  # let the page settle before she reads it
        return await self.extract()

    async def extract(self) -> str:
        """Read the page she is on — its text, not its source."""
        page = await self._ensure_page()
        if page is None:
            raise RuntimeError("browser is not available")
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return (text or "").strip()

    async def screenshot(self, name: str, roots: list[str]) -> str:
        """Capture her view into her workspace (``.lina_eyes/``) and return
        the path, so the fruit is a thing you can open."""
        page = await self._ensure_page()
        if page is None:
            raise RuntimeError("browser is not available")
        save_dir = os.path.join(roots[0], ".lina_eyes")
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, name)
        await page.screenshot(path=path, full_page=False)
        return path

    async def stop(self, exception: Exception | None = None) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        self.available = False
        log.info("[browser] eyes closed cleanly")
