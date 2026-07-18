import csv
import os
import random
from pathlib import Path

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

CSV_PATH = Path(__file__).resolve().parent / "동반출현_전체데이터.csv"
UNIVERSE = range(1, 46)

_combos_by_type = {2: [], 3: [], 4: []}
_number_scores = {}
_number_freq = {}
_mixed_weights = {}


def load_data():
    combos_by_type = {2: [], 3: [], 4: []}

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            count_type = int(row["countType"])
            count = int(row["count"])

            numbers = []
            for i in range(1, 5):
                val = row.get(f"no{i}", "").strip()
                if val:
                    try:
                        numbers.append(int(float(val)))
                    except ValueError:
                        pass

            if not numbers or count_type not in combos_by_type:
                continue

            combos_by_type[count_type].append({"numbers": tuple(numbers), "count": count})

    for combos in combos_by_type.values():
        combos.sort(key=lambda c: c["count"], reverse=True)

    weight_by_type = {2: 1.0, 3: 1.5, 4: 2.0}
    scores = {}
    freq = {}

    for count_type, combos in combos_by_type.items():
        weight = weight_by_type[count_type]
        for combo in combos:
            for num in combo["numbers"]:
                scores[num] = scores.get(num, 0) + combo["count"] * weight
                freq[num] = freq.get(num, 0) + 1

    max_score = max(scores.values()) if scores else 1
    number_scores = {num: round(score / max_score * 100, 1) for num, score in scores.items()}

    max_freq = max(freq.values()) if freq else 1
    normalized_freq = {num: f / max_freq * 100 for num, f in freq.items()}

    mixed_weights = {
        num: (number_scores.get(num, 0) + normalized_freq.get(num, 0)) / 2 for num in UNIVERSE
    }

    return combos_by_type, number_scores, freq, mixed_weights


def parse_exclude(raw):
    excluded = set()
    if not raw:
        return excluded
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            num = int(part)
            if 1 <= num <= 45:
                excluded.add(num)
    return excluded


def pool_for(exclude):
    pool = [n for n in UNIVERSE if n not in exclude]
    # never let exclusions shrink the pool below what a draw needs
    return pool if len(pool) >= 6 else list(UNIVERSE)


def weighted_pick(weights, exclude, k=6):
    """Weighted sampling without replacement (Efraimidis-Spirakis).

    Higher-weight numbers are more *likely* to be picked, but the result
    still varies draw to draw instead of always returning the same top-k.
    """
    pool = pool_for(exclude)
    keyed = []
    for num in pool:
        weight = weights.get(num, 0) + 1  # smoothing: every number keeps a nonzero chance
        key = random.random() ** (1.0 / weight)
        keyed.append((key, num))
    keyed.sort(reverse=True)
    return sorted(num for _, num in keyed[:k])


def draw_numbers(strategy, exclude):
    if strategy == "reliability":
        return weighted_pick(_number_scores, exclude)

    if strategy == "frequency":
        return weighted_pick(_number_freq, exclude)

    if strategy == "mixed":
        return weighted_pick(_mixed_weights, exclude)

    return sorted(random.sample(pool_for(exclude), 6))


def game_stats(numbers):
    odd = sum(1 for n in numbers if n % 2 == 1)
    low = sum(1 for n in numbers if n <= 22)
    return {
        "numbers": numbers,
        "sum": sum(numbers),
        "odd": odd,
        "even": 6 - odd,
        "low": low,
        "high": 6 - low,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/api/draw/<strategy>")
def api_draw(strategy):
    if strategy not in ("reliability", "frequency", "mixed", "random"):
        strategy = "random"

    count = request.args.get("count", 1, type=int) or 1
    count = max(1, min(count, 5))
    exclude = parse_exclude(request.args.get("exclude", ""))

    games = [game_stats(draw_numbers(strategy, exclude)) for _ in range(count)]
    return jsonify({"strategy": strategy, "games": games})


@app.route("/api/stats")
def api_stats():
    top = sorted(_number_scores.items(), key=lambda x: x[1], reverse=True)[:15]
    return jsonify({"top": [{"number": n, "score": s} for n, s in top]})


_combos_by_type, _number_scores, _number_freq, _mixed_weights = load_data()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"

    if debug:
        app.run(debug=True, port=port)
    else:
        from waitress import serve

        print(f"Serving (production) on http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port)
