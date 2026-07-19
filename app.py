import csv
import json
import os
import random
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__)

CSV_PATH = Path(__file__).resolve().parent / "동반출현_전체데이터.csv"
PENSION_PATH = Path(__file__).resolve().parent / "연금복권_전체데이터.json"
UNIVERSE = range(1, 46)
PENSION_GROUPS = range(1, 6)
PENSION_DIGITS = range(10)

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


def load_pension_data():
    with open(PENSION_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)

    rounds = payload["data"]["result"]
    rounds.sort(key=lambda r: r["psltEpsd"])  # oldest first
    total = len(rounds)

    group_freq = {g: 0 for g in PENSION_GROUPS}
    digit_freq = {pos: {d: 0 for d in PENSION_DIGITS} for pos in range(6)}
    group_recency = {g: 0.0 for g in PENSION_GROUPS}
    digit_recency = {pos: {d: 0.0 for d in PENSION_DIGITS} for pos in range(6)}

    for idx, row in enumerate(rounds):
        group = int(row["wnBndNo"])
        number = row["wnRnkVl"].zfill(6)
        recency_weight = (idx + 1) / total  # newer rounds weigh more

        group_freq[group] += 1
        group_recency[group] += recency_weight

        for pos, ch in enumerate(number):
            digit = int(ch)
            digit_freq[pos][digit] += 1
            digit_recency[pos][digit] += recency_weight

    def normalize(weight_map):
        max_w = max(weight_map.values()) if weight_map else 1
        max_w = max_w or 1
        return {k: v / max_w * 100 for k, v in weight_map.items()}

    group_freq_n = normalize(group_freq)
    group_recency_n = normalize(group_recency)
    group_mixed = {g: (group_freq_n[g] + group_recency_n[g]) / 2 for g in PENSION_GROUPS}

    digit_freq_n = {pos: normalize(digit_freq[pos]) for pos in range(6)}
    digit_recency_n = {pos: normalize(digit_recency[pos]) for pos in range(6)}
    digit_mixed = {
        pos: {d: (digit_freq_n[pos][d] + digit_recency_n[pos][d]) / 2 for d in PENSION_DIGITS}
        for pos in range(6)
    }

    return {
        "rounds": rounds,
        "group": {"frequency": group_freq_n, "reliability": group_recency_n, "mixed": group_mixed},
        "digit": {"frequency": digit_freq_n, "reliability": digit_recency_n, "mixed": digit_mixed},
    }


def weighted_choice(weight_map, universe):
    keyed = []
    for item in universe:
        weight = weight_map.get(item, 0) + 1
        key = random.random() ** (1.0 / weight)
        keyed.append((key, item))
    keyed.sort(reverse=True)
    return keyed[0][1]


def draw_pension(strategy):
    if strategy not in ("reliability", "frequency", "mixed"):
        group = random.randint(1, 5)
        number = "".join(str(random.randint(0, 9)) for _ in range(6))
        return group, number

    group_weights = _pension_weights["group"][strategy]
    digit_weights = _pension_weights["digit"][strategy]

    group = weighted_choice(group_weights, PENSION_GROUPS)
    number = "".join(str(weighted_choice(digit_weights[pos], PENSION_DIGITS)) for pos in range(6))
    return group, number


def pension_game_stats(group, number):
    return {
        "group": group,
        "number": number,
        "digitSum": sum(int(d) for d in number),
    }


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


@app.route("/robots.txt")
def robots():
    body = "User-agent: *\nAllow: /\nSitemap: https://lotto-app-m0fe.onrender.com/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    base = "https://lotto-app-m0fe.onrender.com"
    urls = [f"{base}/", f"{base}/privacy"]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        body += f"  <url><loc>{url}</loc></url>\n"
    body += "</urlset>\n"
    return Response(body, mimetype="application/xml")


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


@app.route("/api/pension/draw/<strategy>")
def api_pension_draw(strategy):
    if strategy not in ("reliability", "frequency", "mixed", "random"):
        strategy = "random"

    count = request.args.get("count", 1, type=int) or 1
    count = max(1, min(count, 5))

    games = [pension_game_stats(*draw_pension(strategy)) for _ in range(count)]
    return jsonify({"strategy": strategy, "games": games})


@app.route("/api/pension/stats")
def api_pension_stats():
    group_scores = _pension_weights["group"]["reliability"]
    top_groups = sorted(group_scores.items(), key=lambda x: x[1], reverse=True)
    return jsonify({"groups": [{"group": g, "score": round(s, 1)} for g, s in top_groups]})


_combos_by_type, _number_scores, _number_freq, _mixed_weights = load_data()
_pension_weights = load_pension_data()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"

    if debug:
        app.run(debug=True, port=port)
    else:
        from waitress import serve

        print(f"Serving (production) on http://0.0.0.0:{port}")
        serve(app, host="0.0.0.0", port=port)
