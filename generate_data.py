from __future__ import annotations

import argparse
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static Movie Checker data")
    parser.add_argument("--output", default="site/data/movies.json")
    args = parser.parse_args()

    payload = get_english_showtimes(force_refresh=True)
    movies = all_movies(payload)
    warnings = payload.get("warnings", [])

    # Never replace the last known-good Pages deployment with an empty or
    # obviously misparsed result.
    if not movies:
        detail = "; ".join(warnings) if warnings else "no English-language movie sessions were returned"
        raise RuntimeError("Refusing to deploy empty movie data: " + detail)

    bad = [movie.get("title", "") for movie in movies if movie.get("title", "").strip().casefold() in BAD_TITLES]
    if bad:
        raise RuntimeError("Refusing to deploy suspicious non-movie titles: " + ", ".join(bad))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(movies)} English-language movie entries to {output}")


if __name__ == "__main__":
    main()
