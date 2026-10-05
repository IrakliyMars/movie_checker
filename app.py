from __future__ import annotations

import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from scraper import get_english_showtimes

app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/movies")
def movies():
    force_refresh = request.args.get("refresh") == "1"
    try:
        data = get_english_showtimes(force_refresh=force_refresh)
        return jsonify(data)
    except Exception as exc:
        app.logger.exception("Could not load Yelmo showtimes")
        return (
            jsonify(
                {
                    "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "cinemas": [],
                    "error": str(exc),
                }
            ),
            502,
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
