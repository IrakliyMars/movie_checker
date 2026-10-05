from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

MADRID = ZoneInfo("Europe/Madrid")
YELMO_BASE = "https://www.yelmocines.es"
NOW_PLAYING_URL = f"{YELMO_BASE}/now-playing.aspx/GetNowPlaying"
CITY_KEY = "malaga"
CITY_NAME = "Málaga"

TIME_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d$")
DOTNET_DATE_RE = re.compile(r"/Date\((-?\d+)")
SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

GENERIC_TITLES = {
    "ayuda",
    "cine yelmo",
    "catalogo de peliculas",
    "cambiar de pais",
}


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFD", _clean(value))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Mn").casefold()


def _is_english_format(language: object) -> bool:
    label = _plain(language)
    # Yelmo currently marks its English-subtitled sessions as VOSE. Keep a
    # couple of explicit English labels too, but do not accept generic VO: it
    # can be an original language other than English.
    return any(marker in label for marker in (
        "vose",
        "ingles subtitulado",
        "english subtitled",
        "english",
    ))


def _is_real_title(title: object) -> bool:
    value = _clean(title)
    if not value or len(value) > 180:
        return False
    return _plain(value) not in GENERIC_TITLES


def _date_from_day(day: dict) -> str:
    filter_date = _clean(day.get("FilterDate"))
    match = DOTNET_DATE_RE.search(filter_date)
    if match:
        milliseconds = int(match.group(1))
        local = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).astimezone(MADRID)
        return local.date().isoformat()

    # Fallback for the human label returned by Yelmo, e.g. "6 octubre".
    label = _plain(day.get("ShowtimeDate"))
    match = re.search(r"\b(\d{1,2})\s+([a-z]+)\b", label)
    if match and match.group(2) in SPANISH_MONTHS:
        day_number = int(match.group(1))
        month = SPANISH_MONTHS[match.group(2)]
        today = datetime.now(MADRID).date()
        year = today.year
        # Published schedules can cross New Year.
        if month < today.month - 6:
            year += 1
        elif month > today.month + 6:
            year -= 1
        return f"{year:04d}-{month:02d}-{day_number:02d}"

    raise ValueError(f"Could not parse Yelmo date: {day.get('ShowtimeDate')!r} / {day.get('FilterDate')!r}")


def _cinema_url(cinema: dict) -> str:
    key = _clean(cinema.get("Key"))
    if re.fullmatch(r"[a-z0-9-]+", key):
        return f"{YELMO_BASE}/cartelera/{CITY_KEY}/{key}"
    return f"{YELMO_BASE}/cartelera/{CITY_KEY}/"


def _session_url(showtime: dict, cinema_url: str) -> str:
    cinema_id = _clean(showtime.get("VistaCinemaId"))
    showtime_id = _clean(showtime.get("ShowtimeId"))
    if cinema_id and showtime_id:
        return "https://compra.yelmocines.es/?" + urlencode({
            "cinemaVistaId": cinema_id,
            "showtimeVistaId": showtime_id,
        })
    return cinema_url


def _session_datetime(date_value: str, time_value: str) -> str | None:
    if not TIME_RE.fullmatch(time_value):
        return None
    try:
        value = datetime.fromisoformat(f"{date_value}T{time_value}:00").replace(tzinfo=MADRID)
        return value.isoformat(timespec="minutes")
    except ValueError:
        return None


def _fetch_city(city_key: str) -> dict:
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "content-type": "application/json; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "referer": f"{YELMO_BASE}/cartelera/{city_key}/",
        "origin": YELMO_BASE,
        "user-agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
        ),
    }
    response = requests.post(
        NOW_PLAYING_URL,
        headers=headers,
        json={"cityKey": city_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("d")
    if not isinstance(data, dict):
        raise RuntimeError("Yelmo GetNowPlaying returned an unexpected response")
    return data


def _parse_cinema(raw_cinema: dict) -> dict:
    cinema_name = _clean(raw_cinema.get("Name")) or "Yelmo"
    cinema_url = _cinema_url(raw_cinema)
    movies: dict[str, dict] = {}

    # Crucially, iterate EVERY date Yelmo publishes. There is no arbitrary
    # today-only or 14-day limit here.
    for raw_day in raw_cinema.get("Dates") or []:
        date_value = _date_from_day(raw_day)

        for raw_movie in raw_day.get("Movies") or []:
            title = _clean(raw_movie.get("Title"))
            if not _is_real_title(title):
                continue

            slots: list[dict] = []
            for raw_format in raw_movie.get("Formats") or []:
                language = _clean(raw_format.get("Language"))
                if not _is_english_format(language):
                    continue

                for raw_showtime in raw_format.get("Showtimes") or []:
                    time_value = _clean(raw_showtime.get("Time"))
                    if not TIME_RE.fullmatch(time_value):
                        continue
                    slot = {
                        "time": time_value,
                        "datetime": _session_datetime(date_value, time_value),
                        "url": _session_url(raw_showtime, cinema_url),
                        "format": _clean(raw_format.get("Name") or raw_format.get("Format")),
                    }
                    slots.append(slot)

            if not slots:
                continue

            movie_id = _clean(raw_movie.get("Key")) or title
            key = movie_id.casefold()
            movie = movies.setdefault(key, {
                "id": movie_id,
                "title": title,
                "url": cinema_url,
                "language": "VOSE",
                "dates": {},
            })
            day_slots = movie["dates"].setdefault(date_value, [])
            seen = {(s["time"], s["url"]) for s in day_slots}
            for slot in slots:
                marker = (slot["time"], slot["url"])
                if marker not in seen:
                    seen.add(marker)
                    day_slots.append(slot)

    output_movies = []
    for movie in movies.values():
        dates = []
        for date_value, slots in sorted(movie.pop("dates").items()):
            slots.sort(key=lambda item: (item["time"], item["url"]))
            dates.append({"date": date_value, "showtimes": slots})
        movie["dates"] = dates
        output_movies.append(movie)

    output_movies.sort(key=lambda item: item["title"].casefold())
    return {
        "id": _clean(raw_cinema.get("Key")) or _plain(cinema_name).replace(" ", "-"),
        "name": cinema_name,
        "url": cinema_url,
        "movies": output_movies,
    }


def get_english_showtimes(force_refresh: bool = False) -> dict:
    del force_refresh
    data = _fetch_city(CITY_KEY)
    cinemas = [_parse_cinema(cinema) for cinema in data.get("Cinemas") or []]

    return {
        "updated_at": datetime.now(MADRID).isoformat(timespec="seconds"),
        "source_status": "ok",
        "source": "Yelmo GetNowPlaying",
        "cities": [{
            "id": CITY_KEY,
            "name": CITY_NAME,
            "cinemas": cinemas,
        }],
    }
