import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URLS = [
    "https://www.yelmocines.es/cartelera/malaga/vialia-malaga",
    "https://www.yelmocines.es/cartelera/malaga/plaza-mayor",
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
          const selects=[...document.querySelectorAll('select')].map((s,index)=>({
            index,
            text:n(s.innerText||s.textContent),
            options:[...s.options].map(o=>({value:o.value,text:n(o.textContent),selected:o.selected}))
          }));
          return {url: location.href, title: document.title, bookings, selects};
        }
        """)
        out.append(data)
        page.close()
    browser.close()
Path('debug-output.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
