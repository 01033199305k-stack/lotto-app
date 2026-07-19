import csv
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
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


def analyze_pension(group, number):
    group_score = round(_pension_weights["group"]["reliability"].get(group, 0), 1)
    digit_scores = [
        round(_pension_weights["digit"]["reliability"][pos].get(int(d), 0), 1)
        for pos, d in enumerate(number)
    ]
    avg_digit_score = round(sum(digit_scores) / len(digit_scores), 1) if digit_scores else 0

    return {
        "group": group,
        "number": number,
        "digitSum": sum(int(d) for d in number),
        "groupScore": group_score,
        "digitScores": digit_scores,
        "avgDigitScore": avg_digit_score,
    }


DH_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
LATEST_CACHE_TTL = 1800  # seconds

_latest_cache = {"lotto": None, "pension": None}
_latest_cache_ts = {"lotto": 0.0, "pension": 0.0}


def format_dh_date(yyyymmdd):
    if not yyyymmdd or len(yyyymmdd) != 8:
        return yyyymmdd
    return f"{yyyymmdd[0:4]}.{yyyymmdd[4:6]}.{yyyymmdd[6:8]}"


def _dh_get(url, referer):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DH_USER_AGENT,
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read().decode("utf-8")


def fetch_latest_lotto():
    result_page = "https://www.dhlottery.co.kr/lt645/result"
    html = _dh_get(result_page, result_page)

    match = re.search(r'id="opt_val" value="(\d+)"', html)
    if not match:
        return None
    round_no = match.group(1)

    api_url = f"https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do?srchDir=center&srchLtEpsd={round_no}"
    payload = json.loads(_dh_get(api_url, result_page))
    items = payload.get("data", {}).get("list", [])
    if not items:
        return None

    item = items[0]
    numbers = sorted(item[f"tm{i}WnNo"] for i in range(1, 7))
    return {
        "round": item["ltEpsd"],
        "date": format_dh_date(item["ltRflYmd"]),
        "numbers": numbers,
        "bonus": item["bnsWnNo"],
    }


def fetch_latest_pension():
    result_page = "https://www.dhlottery.co.kr/pt720/result"
    api_url = "https://www.dhlottery.co.kr/pt720/selectPstPt720WnList.do"
    payload = json.loads(_dh_get(api_url, result_page))
    rows = payload.get("data", {}).get("result", [])
    if not rows:
        return None

    latest = max(rows, key=lambda r: r["psltEpsd"])
    return {
        "round": latest["psltEpsd"],
        "date": format_dh_date(latest["psltRflYmd"]),
        "group": int(latest["wnBndNo"]),
        "number": latest["wnRnkVl"].zfill(6),
        "bonus": latest["bnsRnkVl"].zfill(6),
    }


def get_latest(game):
    now = time.time()
    if _latest_cache[game] is not None and now - _latest_cache_ts[game] < LATEST_CACHE_TTL:
        return _latest_cache[game]

    try:
        data = fetch_latest_lotto() if game == "lotto" else fetch_latest_pension()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
        data = None

    if data is not None:
        _latest_cache[game] = data
        _latest_cache_ts[game] = now

    return _latest_cache[game]


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


def analyze_numbers(numbers):
    numbers = sorted(numbers)
    numset = set(numbers)
    odd = sum(1 for n in numbers if n % 2 == 1)
    low = sum(1 for n in numbers if n <= 22)

    scores = {n: round(_number_scores.get(n, 0), 1) for n in numbers}
    avg_score = round(sum(scores.values()) / len(scores), 1) if scores else 0

    best_match = None
    for combos in _combos_by_type.values():
        for combo in combos:
            if set(combo["numbers"]).issubset(numset):
                if best_match is None or combo["count"] > best_match["count"]:
                    best_match = {"numbers": sorted(combo["numbers"]), "count": combo["count"]}

    return {
        "numbers": numbers,
        "sum": sum(numbers),
        "odd": odd,
        "even": 6 - odd,
        "low": low,
        "high": 6 - low,
        "scores": scores,
        "avgScore": avg_score,
        "bestMatch": best_match,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/guide")
def guide():
    return render_template("guide.html")


@app.route("/robots.txt")
def robots():
    body = "User-agent: *\nAllow: /\nSitemap: https://lotto-app-m0fe.onrender.com/sitemap.xml\n"
    return Response(body, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    base = "https://lotto-app-m0fe.onrender.com"
    urls = [f"{base}/", f"{base}/guide", f"{base}/privacy"]
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


@app.route("/api/latest/lotto")
def api_latest_lotto():
    result = get_latest("lotto")
    return jsonify({"ok": result is not None, "result": result})


@app.route("/api/latest/pension")
def api_latest_pension():
    result = get_latest("pension")
    return jsonify({"ok": result is not None, "result": result})


@app.route("/api/analyze")
def api_analyze():
    raw = request.args.get("numbers", "")
    numbers = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            n = int(part)
            if 1 <= n <= 45:
                numbers.add(n)

    if len(numbers) != 6:
        return jsonify({"ok": False, "error": "1~45 사이 서로 다른 번호 6개를 입력해주세요."})

    return jsonify({"ok": True, "result": analyze_numbers(sorted(numbers))})


@app.route("/api/pension/analyze")
def api_pension_analyze():
    group = request.args.get("group", type=int)
    number = request.args.get("number", "")

    if group not in PENSION_GROUPS or not re.fullmatch(r"[0-9]{6}", number or ""):
        return jsonify({"ok": False, "error": "1~5 사이 조와 숫자 6자리를 입력해주세요."})

    return jsonify({"ok": True, "result": analyze_pension(group, number)})


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
