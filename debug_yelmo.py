from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

URLS = [
    "https://www.yelmocines.es/cartelera/malaga/yelmo-cines-vialia-malaga",
    "https://www.yelmocines.es/cartelera/malaga/yelmo-cines-plaza-mayor",
]


def main() -> None:
    output = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="es-ES", timezone_id="Europe/Madrid")

        for url in URLS:
            page = context.new_page()
            responses: list[dict] = []

            def on_response(response):
                ct = (response.headers.get("content-type") or "").lower()
                u = response.url
                if any(token in u.lower() for token in ("api", "show", "session", "movie", "film", "cinema", "schedule", "cartelera", "vista")) or "json" in ct:
                    item = {"url": u, "status": response.status, "content_type": ct}
                    if "json" in ct:
                        try:
                            body = response.text()
                            item["body_sample"] = body[:4000]
                        except Exception:
                            pass
                    responses.append(item)

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)

            info = page.evaluate(
                """
                () => {
                  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
                  const attrs = (el) => ({
                    tag: el?.tagName || null,
                    id: el?.id || null,
                    className: typeof el?.className === 'string' ? el.className : null,
                    role: el?.getAttribute?.('role') || null,
                    href: el?.getAttribute?.('href') || null,
                    text: norm(el?.innerText || el?.textContent || '').slice(0, 700),
                  });

                  const booking = [...document.querySelectorAll('a[href]')]
                    .filter(a => /compra\.yelmocines\.es|showtimeVistaId|cinemaVistaId/i.test(a.href))
                    .slice(0, 40)
                    .map(a => {
                      const chain = [];
                      let el = a;
                      for (let i = 0; i < 8 && el; i++, el = el.parentElement) chain.push(attrs(el));
                      return {anchor: attrs(a), chain};
                    });

                  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5')]
                    .map(h => {
                      const text = norm(h.innerText || h.textContent);
                      if (!text) return null;
                      const chain = [];
                      let el = h;
                      for (let i = 0; i < 5 && el; i++, el = el.parentElement) chain.push(attrs(el));
                      return {heading: attrs(h), chain};
                    })
                    .filter(Boolean);

                  const selects = [...document.querySelectorAll('select')].map(select => ({
                    el: attrs(select),
                    name: select.name || null,
                    value: select.value || null,
                    options: [...select.options].map(o => ({value:o.value, text:norm(o.textContent), selected:o.selected})),
                  }));

                  const dateish = [...document.querySelectorAll('button, a, label, option, [data-date], [datetime]')]
                    .filter(el => /\b(?:0?[1-9]|[12]\d|3[01])\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b/i.test(norm(el.textContent)))
                    .slice(0, 80)
                    .map(attrs);

                  return {title: document.title, booking, headings, selects, dateish};
                }
                """
            )
            info["page_url"] = page.url
            info["responses"] = responses[-120:]
            output.append(info)
            page.close()

        browser.close()

    Path("debug-output.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
