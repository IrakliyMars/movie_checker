import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS = [
    "https://www.yelmocines.es/cartelera/malaga/yelmo-cines-vialia-malaga",
    "https://www.yelmocines.es/cartelera/malaga/yelmo-cines-plaza-mayor",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(locale="es-ES", timezone_id="Europe/Madrid")
    out = []
    for url in URLS:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(7000)
        data = page.evaluate("""
        () => {
          const n = s => (s || '').replace(/\s+/g,' ').trim();
          const info = el => ({
            tag: el?.tagName || null,
            cls: typeof el?.className === 'string' ? el.className : null,
            id: el?.id || null,
            text: n(el?.innerText || el?.textContent || '').slice(0,1000),
            href: el?.getAttribute?.('href') || null,
            dataDate: el?.getAttribute?.('data-date') || null,
            dataDay: el?.getAttribute?.('data-day') || null,
            datetime: el?.getAttribute?.('datetime') || null,
            ariaSelected: el?.getAttribute?.('aria-selected') || null,
            role: el?.getAttribute?.('role') || null,
          });
          const bookings = [...document.querySelectorAll('a[href]')]
            .filter(a => /compra\.yelmocines\.es|showtimeVistaId|cinemaVistaId/i.test(a.href))
            .slice(0,25)
            .map(a => {
              let el=a, chain=[];
              for(let i=0;i<10 && el;i++,el=el.parentElement) chain.push(info(el));
              return chain;
            });
          const controls=[...document.querySelectorAll('button,a,[role="tab"],[data-date],[data-day],[datetime]')]
            .map(info)
            .filter(x => x.text && x.text.length < 80)
            .filter(x => /hoy|mañana|lun|mar|mi[eé]|jue|vie|s[aá]b|dom|\b\d{1,2}[\/-]\d{1,2}\b|\b\d{1,2}\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)/i.test(x.text) || x.dataDate || x.dataDay || x.datetime)
            .slice(0,100);
          return {url: location.href, title: document.title, bookings, controls};
        }
        """)
        out.append(data)
        page.close()
    browser.close()
Path('debug-output.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
