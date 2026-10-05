from __future__ import annotations

import argparse
import json
from pathlib import Path

from scraper import get_english_showtimes


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static Movie Checker data")
    parser.add_argument("--output", default="site/data/movies.json")
    args = parser.parse_args()

    payload = get_english_showtimes(force_refresh=True)
    cinemas = payload.get("cinemas", [])
    movie_count = sum(len(cinema.get("movies", [])) for cinema in cinemas)
    warnings = payload.get("warnings", [])

    # If scraping clearly failed, abort the deployment. GitHub Pages then keeps
    # serving the previous successful deployment instead of replacing it with
    # an empty/broken one.
    if warnings and movie_count == 0:
        raise RuntimeError("Scraper returned no movies and reported errors: " + "; ".join(warnings))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {movie_count} movies to {output}")


if __name__ == "__main__":
    main()
