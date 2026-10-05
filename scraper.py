from __future__ import annotations

import re
import threading
import time
from copy import deepcopy
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
)
TIME_RE = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b")

_CACHE_TTL_SECONDS = 10 * 60
_cache_lock = threading.Lock()
_cache_value: dict | None = None
_cache_time = 0.0


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _absolute(base_url: str, href: str | None) -> str:
    if not href or href.startswith("javascript:") or href == "#":
        return base_url
    return urljoin(base_url, href)


def _extract_cinema(page, cinema: dict) -> dict:
    """Extract English/VOSE films with clickable film and showtime links."""

    items = page.evaluate(
        """
        ({ markers }) => {
          const timeRe = /\\b(?:[01]?\\d|2[0-3]):[0-5]\\d\\b/g;
          const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const upper = (s) => norm(s).toLocaleUpperCase('es-ES');
          const isEnglish = (s) => markers.some((m) => upper(s).includes(m));
          const headings = [...document.querySelectorAll('h2, h3, h4')];
          const result = [];

          for (const heading of headings) {
            const title = norm(heading.textContent);
            if (!title || title.length > 180) continue;

            let card = heading;
            for (let i = 0; i < 9 && card; i++, card = card.parentElement) {
              const text = norm(card.innerText);
              const hasTimes = (text.match(timeRe) || []).length > 0;
              if (isEnglish(text) && hasTimes && text.length < 3500) break;
            }
            if (!card || !isEnglish(card.innerText)) continue;

            const filmAnchor = heading.closest('a[href]')
              || card.querySelector('a[href*="pelicula"], a[href*="movie"], a[href*="film"], a[href*="detalle"]');
            const filmHref = filmAnchor ? filmAnchor.getAttribute('href') : null;

            const all = [...card.querySelectorAll('*')];
            const languageNodes = all.filter((el) => {
              const t = upper(el.textContent);
              if (!isEnglish(t)) return false;
              return ![...el.children].some((child) => isEnglish(child.textContent));
            });

            const showtimes = [];
            const seen = new Set();

            for (const lang of languageNodes) {
              let block = lang;
              for (let i = 0; i < 5 && block; i++, block = block.parentElement) {
                const text = norm(block.innerText);
                const anchors = [...block.querySelectorAll('a[href]')]
                  .filter((a) => timeRe.test(norm(a.textContent)));
                timeRe.lastIndex = 0;
                if (anchors.length && text.length < 900) {
                  for (const a of anchors) {
                    const times = norm(a.textContent).match(timeRe) || [];
                    for (const time of times) {
                      const key = `${time}|${a.getAttribute('href') || ''}`;
                      if (!seen.has(key)) {
                        seen.add(key);
                        showtimes.push({ time, href: a.getAttribute('href') });
                      }
                    }
                  }
                  break;
                }
              }
            }

            if (!showtimes.length) {
              const text = norm(card.innerText);
              const markerPos = markers
                .map((m) => upper(text).indexOf(m))
                .filter((n) => n >= 0)
                .sort((a, b) => a - b)[0];
              if (markerPos !== undefined) {
                const tail = text.slice(markerPos, markerPos + 500);
                const times = [...new Set(tail.match(timeRe) || [])];
                for (const time of times) showtimes.push({ time, href: null });
              }
            }

            if (showtimes.length) {
              result.push({ title, filmHref, showtimes });
            }
          }

          const deduped = new Map();
          for (const item of result) {
            const key = item.title.toLocaleLowerCase('es-ES');
            if (!deduped.has(key)) deduped.set(key, item);
            else {
              const current = deduped.get(key);
              const byKey = new Map(current.showtimes.map((s) => [`${s.time}|${s.href || ''}`, s]));
              for (const s of item.showtimes) byKey.set(`${s.time}|${s.href || ''}`, s);
              current.showtimes = [...byKey.values()];
            }
          }
          return [...deduped.values()];
        }
        """,
        {"markers": [m.upper() for m in ENGLISH_MARKERS]},
    )

    films = []
    for item in items:
        title = _clean(item.get("title"))
        if not title:
            continue

        film_url = _absolute(cinema["url"], item.get("filmHref"))
        showtimes = []
        seen_times = set()
        for showtime in item.get("showtimes", []):
            time_text = _clean(showtime.get("time"))
            if not TIME_RE.fullmatch(time_text) or time_text in seen_times:
                continue
            seen_times.add(time_text)
            direct_url = _absolute(cinema["url"], showtime.get("href"))
            if direct_url == cinema["url"] and film_url != cinema["url"]:
                direct_url = film_url
            showtimes.append({"time": time_text, "url": direct_url})

        if showtimes:
            showtimes.sort(key=lambda entry: entry["time"])
            films.append(
                {
                    "title": title,
                    "url": film_url,
                    "language": "VOSE",
                    "showtimes": showtimes,
                }
            )

    films.sort(key=lambda film: film["title"].casefold())
    return {"name": cinema["name"], "url": cinema["url"], "movies": films}


def _scrape() -> dict:
    cinemas = []
    errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0 Safari/537.36"
            ),
        )

        for cinema in CINEMAS:
            page = context.new_page()
            try:
                page.goto(cinema["url"], wait_until="domcontentloaded", timeout=30_000)
                try:
                    page.wait_for_function(
                        """
                        () => {
                          const text = document.body ? document.body.innerText : '';
                          return !text.includes('Loading...') && /\\b\\d{1,2}:\\d{2}\\b/.test(text);
                        }
                        """,
                        timeout=12_000,
                    )
                except PlaywrightTimeoutError:
                    page.wait_for_timeout(2_500)

                cinemas.append(_extract_cinema(page, cinema))
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


def get_english_showtimes(force_refresh: bool = False) -> dict:
    global _cache_time, _cache_value

    with _cache_lock:
        now = time.monotonic()
        if (
            not force_refresh
            and _cache_value is not None
            and now - _cache_time < _CACHE_TTL_SECONDS
        ):
            return deepcopy(_cache_value)

        value = _scrape()
        _cache_value = deepcopy(value)
        _cache_time = now
        return value
