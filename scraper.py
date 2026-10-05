from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

MADRID = ZoneInfo("Europe/Madrid")

CINEMAS = [
    {
        "name": "Vialia Málaga",
        "url": "https://www.yelmocines.es/cartelera/malaga/vialia-malaga",
    },
    {
        "name": "Plaza Mayor",
        "url": "https://www.yelmocines.es/cartelera/malaga/plaza-mayor",
    },
    {
        "name": "Rincón de la Victoria",
        "url": "https://www.yelmocines.es/cartelera/malaga/rincon-de-la-victoria",
    },
]

ENGLISH_MARKERS = (
    "INGLÉS SUBTITULADO EN ESPAÑOL",
    "INGLES SUBTITULADO EN ESPAÑOL",
    "INGLÉS (VOSE)",
    "INGLES (VOSE)",
    "VOSE",
)
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")

GENERIC_TITLES = {
    "CINES", "HORARIOS", "DÍA", "DIA", "TIPO PROYECCIÓN", "TIPO PROYECCION",
    "FORMATO", "EXPERIENCIA", "IDIOMA", "PRÓXIMOS ESTRENOS", "PROXIMOS ESTRENOS",
    "CATÁLOGO DE PELÍCULAS", "CATALOGO DE PELICULAS", "CAMBIAR DE PAÍS", "CAMBIAR DE PAIS",
    "CINE YELMO", "POLÍTICAS", "POLITICAS", "AYUDA", "INFORMACIÓN DE CINE",
    "INFORMACION DE CINE", "POLÍTICAS Y REGLAS DE ADMISIÓN", "POLITICAS Y REGLAS DE ADMISION",
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _absolute(base_url: str, href: str | None) -> str:
    if not href or href.startswith("javascript:") or href == "#":
        return base_url
    return urljoin(base_url, href)


def _is_real_title(value: str) -> bool:
    title = _clean(value)
    upper = title.upper()
    if not title or len(title) > 150:
        return False
    if upper in GENERIC_TITLES:
        return False
    if upper.endswith(" - MÁLAGA") or upper.endswith(" - MALAGA"):
        return False
    if any(marker in upper for marker in ENGLISH_MARKERS):
        return False
    return True


def _find_day_select(page) -> int | None:
    return page.evaluate(
        """
        () => {
          const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
          const selects = [...document.querySelectorAll('select')];
          let best = null, bestScore = -1;
          for (let i = 0; i < selects.length; i++) {
            const select = selects[i];
            const options = [...select.options].map(o => norm(o.textContent));
            let score = options.length >= 2 ? 1 : 0;
            let parent = select.parentElement, nearby = '';
            for (let d = 0; d < 4 && parent; d++, parent = parent.parentElement) nearby += ' ' + norm(parent.innerText || parent.textContent);
            if (/\bD[IÍ]A\b/i.test(nearby)) score += 5;
            score += Math.min(options.filter(t => /HOY|MAÑANA|LUN|MAR|MI[EÉ]|JUE|VIE|S[AÁ]B|DOM|\d{1,2}[\/-]\d{1,2}|\d{4}-\d{2}-\d{2}/i.test(t)).length, 4);
            if (score > bestScore) { bestScore = score; best = i; }
          }
          return bestScore >= 5 ? best : null;
        }
        """
    )


def _day_options(page, select_index: int) -> list[dict]:
    return page.evaluate(
        """
        (index) => {
          const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
          const select = document.querySelectorAll('select')[index];
          if (!select) return [];
          return [...select.options].map((o, i) => ({index:i, value:o.value, text:norm(o.textContent), disabled:o.disabled}))
            .filter(o => !o.disabled && o.text && o.value !== '');
        }
        """,
        select_index,
    )


def _normalize_date_label(value: str, text: str) -> str:
    value, text = _clean(value), _clean(text)
    for candidate in (value, text):
        match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", candidate)
        if match:
            y, m, d = map(int, match.groups())
            return f"{y:04d}-{m:02d}-{d:02d}"
    today = datetime.now(MADRID).date()
    if text.upper() == "HOY":
        return today.isoformat()
    if text.upper() in {"MAÑANA", "MANANA"}:
        from datetime import timedelta
        return (today + timedelta(days=1)).isoformat()
    return text or value or today.isoformat()


def _extract_visible_movies(page, cinema: dict, date_label: str) -> list[dict]:
    rows = page.evaluate(
        """
        ({ markers }) => {
          const norm = s => (s || '').replace(/\s+/g, ' ').trim();
          const upper = s => norm(s).toLocaleUpperCase('es-ES');
          const isEnglish = s => markers.some(m => upper(s).includes(m));
          const timeRe = /\b(?:[01]?\d|2[0-3]):[0-5]\d\b/;
          const isBooking = a => /compra\.yelmocines\.es|showtimeVistaId|cinemaVistaId/i.test(a.getAttribute('href') || '');
          const result = [];

          for (const heading of [...document.querySelectorAll('h3')]) {
            const title = norm(heading.innerText || heading.textContent);
            if (!title) continue;
            let card = heading, chosen = null;
            for (let depth = 0; depth < 8 && card; depth++, card = card.parentElement) {
              const h3s = [...card.querySelectorAll('h3')];
              const bookings = [...card.querySelectorAll('a[href]')].filter(isBooking);
              const text = norm(card.innerText || card.textContent);
              if (h3s.length === 1 && bookings.length && text.length < 2200) { chosen = card; break; }
            }
            if (!chosen || !isEnglish(norm(chosen.innerText || chosen.textContent))) continue;

            const headingLink = heading.closest('a[href]') || heading.querySelector('a[href]');
            const showtimes = [];
            const seen = new Set();
            for (const markerEl of [...chosen.querySelectorAll('*')].filter(el => {
              const t = norm(el.innerText || el.textContent);
              return isEnglish(t) && ![...el.children].some(c => isEnglish(norm(c.innerText || c.textContent)));
            })) {
              let block = markerEl;
              for (let depth = 0; depth < 6 && block && chosen.contains(block); depth++, block = block.parentElement) {
                const anchors = [...block.querySelectorAll('a[href]')].filter(a => isBooking(a) && timeRe.test(norm(a.innerText || a.textContent)));
                if (!anchors.length) continue;
                for (const a of anchors) {
                  const m = norm(a.innerText || a.textContent).match(timeRe);
                  if (!m) continue;
                  const key = `${m[0]}|${a.getAttribute('href') || ''}`;
                  if (seen.has(key)) continue;
                  seen.add(key);
                  showtimes.push({time:m[0], href:a.getAttribute('href')});
                }
                break;
              }
            }
            if (showtimes.length) result.push({title, filmHref: headingLink?.getAttribute('href') || null, showtimes});
          }
          return result;
        }
        """,
        {"markers": [m.upper() for m in ENGLISH_MARKERS]},
    )

    movies = []
    for row in rows:
        title = _clean(row.get("title"))
        if not _is_real_title(title):
            continue
        slots, seen = [], set()
        for raw in row.get("showtimes", []):
            time_text = _clean(raw.get("time"))
            url = _absolute(cinema["url"], raw.get("href"))
            if not TIME_RE.fullmatch(time_text):
                continue
            key = (time_text, url)
            if key in seen:
                continue
            seen.add(key)
            slots.append({"time": time_text, "url": url})
        if slots:
            slots.sort(key=lambda x: x["time"])
            movies.append({"title": title, "url": _absolute(cinema["url"], row.get("filmHref")), "language": "VOSE", "dates": [{"date": date_label, "showtimes": slots}]})
    return movies


def _merge_movies(target: dict[str, dict], items: list[dict]) -> None:
    for item in items:
        key = item["title"].casefold()
        if key not in target:
            target[key] = item
            continue
        existing = target[key]
        for day in item["dates"]:
            current = next((d for d in existing["dates"] if d["date"] == day["date"]), None)
            if current is None:
                existing["dates"].append(day)
                continue
            seen = {(s["time"], s["url"]) for s in current["showtimes"]}
            for slot in day["showtimes"]:
                if (slot["time"], slot["url"]) not in seen:
                    current["showtimes"].append(slot)
            current["showtimes"].sort(key=lambda s: s["time"])


def _scrape_cinema(page, cinema: dict) -> dict:
    page.goto(cinema["url"], wait_until="domcontentloaded", timeout=30_000)
    try:
        page.wait_for_function("""() => [...document.querySelectorAll('a[href]')].some(a => /showtimeVistaId|compra\.yelmocines\.es/i.test(a.href))""", timeout=15_000)
    except PlaywrightTimeoutError:
        page.wait_for_timeout(3000)

    merged: dict[str, dict] = {}
    select_index = _find_day_select(page)
    if select_index is None:
        _merge_movies(merged, _extract_visible_movies(page, cinema, datetime.now(MADRID).date().isoformat()))
    else:
        options = _day_options(page, select_index)
        for option in options[:14] or [{"index": 0, "value": "", "text": "HOY"}]:
            if options:
                locator = page.locator("select").nth(select_index)
                try:
                    locator.select_option(value=option["value"])
                except Exception:
                    locator.select_option(index=option["index"])
                page.wait_for_timeout(1100)
            _merge_movies(merged, _extract_visible_movies(page, cinema, _normalize_date_label(option["value"], option["text"])))

    movies = list(merged.values())
    for movie in movies:
        movie["dates"].sort(key=lambda d: d["date"])
    movies.sort(key=lambda m: m["title"].casefold())
    return {"name": cinema["name"], "url": cinema["url"], "movies": movies}


def get_english_showtimes(force_refresh: bool = False) -> dict:
    del force_refresh
    cinemas, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="es-ES", timezone_id="Europe/Madrid", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36")
        for cinema in CINEMAS:
            page = context.new_page()
            try:
                cinemas.append(_scrape_cinema(page, cinema))
            except Exception as exc:
                errors.append(f"{cinema['name']}: {exc}")
                cinemas.append({"name": cinema["name"], "url": cinema["url"], "movies": []})
            finally:
                page.close()
        context.close()
        browser.close()

    payload = {"updated_at": datetime.now(MADRID).isoformat(timespec="seconds"), "cities": [{"id": "malaga", "name": "Málaga", "cinemas": cinemas}]}
    if errors:
        payload["warnings"] = errors
    return payload
