from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

CINEMAS = [
    {
        "name": "Vialia Málaga",
        "url": "https://www.yelmocines.es/cartelera/malaga/yelmo-cines-vialia-malaga",
    },
    {
        "name": "Plaza Mayor",
        "url": "https://www.yelmocines.es/cartelera/malaga/yelmo-cines-plaza-mayor",
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

# Date selectors on Yelmo are short controls (e.g. HOY, LUN 5, MAR 6, 05/10).
DATE_TEXT_RE = re.compile(
    r"^(?:HOY|MAÑANA|LUN(?:ES)?|MAR(?:TES)?|MI[EÉ](?:RCOLES)?|JUE(?:VES)?|VIE(?:RNES)?|S[AÁ]B(?:ADO)?|DOM(?:INGO)?|"
    r"(?:LUN|MAR|MI[EÉ]|JUE|VIE|S[AÁ]B|DOM)\s*\d{1,2}|"
    r"\d{1,2}\s*(?:ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC)|"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)$",
    re.IGNORECASE,
)

GENERIC_TITLES = {
    "AYUDA",
    "CAMBIAR DE PAÍS",
    "CAMBIAR DE PAIS",
    "CATÁLOGO DE PELÍCULAS",
    "CATALOGO DE PELICULAS",
    "CINE YELMO",
    "INFORMACIÓN DE CINE",
    "INFORMACION DE CINE",
    "INGRESA TUS DATOS",
    "POLÍTICAS",
    "POLITICAS",
    "POLÍTICAS Y REGLAS DE ADMISIÓN",
    "POLITICAS Y REGLAS DE ADMISION",
    "PRÓXIMOS ESTRENOS",
    "PROXIMOS ESTRENOS",
}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _absolute(base_url: str, href: str | None) -> str:
    if not href or href.startswith("javascript:") or href == "#":
        return base_url
    return urljoin(base_url, href)


def _looks_like_real_title(title: str) -> bool:
    value = _clean(title)
    upper = value.upper()
    if not value or len(value) > 140:
        return False
    if upper in GENERIC_TITLES:
        return False
    if upper.endswith(" - MÁLAGA") or upper.endswith(" - MALAGA"):
        return False
    if any(marker in upper for marker in ENGLISH_MARKERS):
        return False
    return True


def _date_controls(page) -> list[dict]:
    """Return likely schedule-date controls without clicking unrelated navigation."""
    controls = page.evaluate(
        """
        () => {
          const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
          const selectors = 'button,[role="tab"],[data-date],[data-day],[datetime]';
          return [...document.querySelectorAll(selectors)].map((el, index) => ({
            index,
            text: norm(el.innerText || el.textContent),
            dataDate: el.getAttribute('data-date'),
            dataDay: el.getAttribute('data-day'),
            datetime: el.getAttribute('datetime'),
            ariaLabel: el.getAttribute('aria-label'),
            title: el.getAttribute('title'),
            disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
          }));
        }
        """
    )

    result: list[dict] = []
    seen = set()
    for control in controls:
        if control.get("disabled"):
            continue
        text = _clean(control.get("text"))
        attrs = [
            _clean(control.get("dataDate")),
            _clean(control.get("dataDay")),
            _clean(control.get("datetime")),
            _clean(control.get("ariaLabel")),
            _clean(control.get("title")),
        ]
        has_date_attr = any(re.search(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b", a) for a in attrs if a)
        if not ((text and len(text) <= 24 and DATE_TEXT_RE.fullmatch(text)) or has_date_attr):
            continue
        key = tuple([text, *attrs])
        if key in seen:
            continue
        seen.add(key)
        control["label"] = next((a for a in attrs[:3] if a), text)
        result.append(control)
    return result[:14]


def _current_date_label(page) -> str:
    value = page.evaluate(
        """
        () => {
          const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
          const active = document.querySelector(
            '[data-date][aria-selected="true"], [data-day][aria-selected="true"], [role="tab"][aria-selected="true"], .active[data-date], .active[data-day], button.active'
          );
          if (!active) return null;
          return active.getAttribute('data-date') || active.getAttribute('data-day') || active.getAttribute('datetime') || norm(active.innerText || active.textContent);
        }
        """
    )
    return _clean(value) or datetime.now().astimezone().date().isoformat()


def _extract_visible_movies(page, cinema: dict, date_label: str) -> list[dict]:
    """Start from actual booking links, then find the smallest VOSE movie card around each link."""
    rows = page.evaluate(
        """
        ({ markers }) => {
          const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
          const upper = (s) => norm(s).toLocaleUpperCase('es-ES');
          const isEnglish = (s) => markers.some((m) => upper(s).includes(m));
          const timeRe = /\b(?:[01]?\d|2[0-3]):[0-5]\d\b/;

          const bookingAnchors = [...document.querySelectorAll('a[href]')].filter((a) => {
            const href = a.getAttribute('href') || '';
            const text = norm(a.innerText || a.textContent);
            return timeRe.test(text) && /compra\.yelmocines\.es|showtimeVistaId|cinemaVistaId/i.test(href);
          });

          const out = [];
          for (const anchor of bookingAnchors) {
            const timeMatch = norm(anchor.innerText || anchor.textContent).match(timeRe);
            if (!timeMatch) continue;

            let card = anchor;
            let chosen = null;
            for (let depth = 0; depth < 9 && card; depth++, card = card.parentElement) {
              const text = norm(card.innerText || card.textContent);
              if (!isEnglish(text) || text.length > 2200) continue;

              const bookingCount = [...card.querySelectorAll('a[href]')].filter((a) => {
                const href = a.getAttribute('href') || '';
                return /compra\.yelmocines\.es|showtimeVistaId|cinemaVistaId/i.test(href);
              }).length;

              const headings = [...card.querySelectorAll('h1,h2,h3,h4,h5,[class*="title" i]')]
                .map((el) => norm(el.innerText || el.textContent))
                .filter(Boolean)
                .filter((t) => !isEnglish(t) && t.length <= 160);

              if (bookingCount >= 1 && headings.length >= 1) {
                chosen = {card, headings};
                break;
              }
            }
            if (!chosen) continue;

            const { card: movieCard, headings } = chosen;
            let title = headings.find((t) => !timeRe.test(t)) || headings[0];

            // Prefer a link around the title; otherwise keep the cinema URL as fallback.
            let filmHref = null;
            const titleEls = [...movieCard.querySelectorAll('h1,h2,h3,h4,h5,[class*="title" i]')];
            for (const el of titleEls) {
              if (norm(el.innerText || el.textContent) !== title) continue;
              const link = el.closest('a[href]') || el.querySelector('a[href]');
              if (link) {
                filmHref = link.getAttribute('href');
                break;
              }
            }

            out.push({
              title,
              filmHref,
              time: timeMatch[0],
              showtimeHref: anchor.getAttribute('href'),
            });
          }
          return out;
        }
        """,
        {"markers": [m.upper() for m in ENGLISH_MARKERS]},
    )

    movies: dict[str, dict] = {}
    for row in rows:
        title = _clean(row.get("title"))
        if not _looks_like_real_title(title):
            continue
        film_url = _absolute(cinema["url"], row.get("filmHref"))
        showtime_url = _absolute(cinema["url"], row.get("showtimeHref"))
        time_text = _clean(row.get("time"))
        if not TIME_RE.fullmatch(time_text):
            continue

        key = title.casefold()
        movie = movies.setdefault(
            key,
            {
                "title": title,
                "url": film_url,
                "language": "VOSE",
                "dates": [{"date": date_label, "showtimes": []}],
            },
        )
        slots = movie["dates"][0]["showtimes"]
        if not any(slot["time"] == time_text and slot["url"] == showtime_url for slot in slots):
            slots.append({"time": time_text, "url": showtime_url})

    result = list(movies.values())
    for movie in result:
        movie["dates"][0]["showtimes"].sort(key=lambda s: s["time"])
    return result


def _merge_date_movies(target: dict[str, dict], items: list[dict]) -> None:
    for item in items:
        key = item["title"].casefold()
        if key not in target:
            target[key] = item
            continue
        existing = target[key]
        if existing.get("url", "").endswith("cartelera") and item.get("url"):
            existing["url"] = item["url"]
        for day in item.get("dates", []):
            if not any(d.get("date") == day.get("date") for d in existing["dates"]):
                existing["dates"].append(day)


def _scrape_cinema(page, cinema: dict) -> dict:
    page.goto(cinema["url"], wait_until="domcontentloaded", timeout=30_000)
    try:
        page.wait_for_function(
            """() => [...document.querySelectorAll('a[href]')].some(a => /showtimeVistaId|compra\.yelmocines\.es/i.test(a.href))""",
            timeout=15_000,
        )
    except PlaywrightTimeoutError:
        page.wait_for_timeout(3_000)

    merged: dict[str, dict] = {}

    # Always scrape the initially selected date.
    initial_date = _current_date_label(page)
    _merge_date_movies(merged, _extract_visible_movies(page, cinema, initial_date))

    # Then visit each visible date selector. Re-discover the DOM before every click,
    # because Yelmo may rerender the schedule after selecting a date.
    descriptors = _date_controls(page)
    for descriptor in descriptors:
        text = _clean(descriptor.get("text"))
        data_date = _clean(descriptor.get("dataDate"))
        data_day = _clean(descriptor.get("dataDay"))
        datetime_value = _clean(descriptor.get("datetime"))

        clicked = page.evaluate(
            """
            ({ text, dataDate, dataDay, datetimeValue }) => {
              const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
              const candidates = [...document.querySelectorAll('button,[role="tab"],[data-date],[data-day],[datetime]')];
              const el = candidates.find((node) => {
                if (dataDate && node.getAttribute('data-date') === dataDate) return true;
                if (dataDay && node.getAttribute('data-day') === dataDay) return true;
                if (datetimeValue && node.getAttribute('datetime') === datetimeValue) return true;
                return text && norm(node.innerText || node.textContent) === text;
              });
              if (!el) return false;
              el.click();
              return true;
            }
            """,
            {"text": text, "dataDate": data_date, "dataDay": data_day, "datetimeValue": datetime_value},
        )
        if not clicked:
            continue
        page.wait_for_timeout(900)
        date_label = data_date or data_day or datetime_value or text or _current_date_label(page)
        items = _extract_visible_movies(page, cinema, date_label)
        _merge_date_movies(merged, items)

    movies = list(merged.values())
    for movie in movies:
        movie["dates"].sort(key=lambda d: d.get("date", ""))
    movies.sort(key=lambda movie: movie["title"].casefold())
    return {"name": cinema["name"], "url": cinema["url"], "movies": movies}


def get_english_showtimes(force_refresh: bool = False) -> dict:
    del force_refresh  # Kept for compatibility with the static generator.
    cinemas = []
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
            ),
        )

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

    payload = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cinemas": cinemas,
    }
    if errors:
        payload["warnings"] = errors
    return payload
