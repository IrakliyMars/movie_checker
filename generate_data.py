from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from scraper import get_english_showtimes

BAD_TITLES = {
    "ayuda",
    "cine yelmo",
    "catálogo de películas",
    "catalogo de peliculas",
    "cambiar de país",
    "cambiar de pais",
}


def all_movies(payload: dict) -> list[dict]:
    movies = []
    if isinstance(payload.get("cities"), list):
        for city in payload["cities"]:
            for cinema in city.get("cinemas", []):
                movies.extend(cinema.get("movies", []))
    else:
        for cinema in payload.get("cinemas", []):
            movies.extend(cinema.get("movies", []))
    return movies


def remove_bad_titles(payload: dict) -> list[str]:
    removed: list[str] = []
    cities = payload.get("cities") if isinstance(payload.get("cities"), list) else None
    containers = cities if cities is not None else [{"cinemas": payload.get("cinemas", [])}]
    for city in containers:
        for cinema in city.get("cinemas", []):
            clean = []
            for movie in cinema.get("movies", []):
                title = str(movie.get("title", "")).strip()
                if title.casefold() in BAD_TITLES:
                    removed.append(title)
                    continue
                clean.append(movie)
            cinema["movies"] = clean
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static Movie Checker data")
    parser.add_argument("--output", default="site/data/movies.json")
    args = parser.parse_args()

    try:
        payload = get_english_showtimes(force_refresh=True)
    except Exception as exc:
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "cities": [{"id": "malaga", "name": "Málaga", "cinemas": []}],
            "warnings": [f"Source error: {type(exc).__name__}: {exc}"],
        }

    removed = remove_bad_titles(payload)
    movies = all_movies(payload)
    warnings = list(payload.get("warnings", []))
    if removed:
        warnings.append("Filtered non-movie titles: " + ", ".join(sorted(set(removed))))

    # External source failures must not make the GitHub Pages deployment fail.
    # Publish an explicit source status so the frontend does not confuse a
    # scraping outage with a genuine 'no English sessions' result.
    payload["source_status"] = "ok" if movies else "unavailable"
    payload["warnings"] = warnings
    if not payload.get("updated_at"):
        payload["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(movies)} English-language movie entries to {output}; source_status={payload['source_status']}")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
