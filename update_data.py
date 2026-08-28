"""동반출현 분석 데이터를 최신 회차까지 갱신한다.

`동반출현_전체데이터.csv`는 정적 파일이라 새 회차가 나와도 저절로 늘지 않는다.
신뢰도 점수가 이 파일에서 나오므로, 갱신하지 않으면 사이트의 분석이 계속 낡는다.

사용법:
    python update_data.py           # 새 회차만 반영
    python update_data.py --dry-run # 무엇이 반영될지만 출력

반영 후에는 커밋·푸시해야 실제 사이트에 적용된다.
"""

import csv
import json
import re
import sys
import urllib.request
from itertools import combinations
from pathlib import Path

# 윈도우 콘솔 기본 인코딩(cp949)은 em dash 같은 문자를 못 찍고 죽는다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "동반출현_전체데이터.csv"
PENSION_PATH = BASE / "연금복권_전체데이터.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
LOTTO_REFERER = "https://www.dhlottery.co.kr/lt645/result"
LOTTO_API = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"
PENSION_REFERER = "https://www.dhlottery.co.kr/pt720/result"
PENSION_API = "https://www.dhlottery.co.kr/pt720/selectPstPt720WnList.do"

FIELDS = ["countType", "count", "recentRound", "recentDate", "no1", "no2", "no3", "no4"]


def get_json(url, referer):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": referer, "X-Requested-With": "XMLHttpRequest"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_draw(item):
    return {
        "round": int(item["ltEpsd"]),
        "date": item["ltRflYmd"],
        "numbers": sorted(item[f"tm{i}WnNo"] for i in range(1, 7)),
    }


def fetch_latest_round():
    """최신 회차 번호. 목록 API는 시작 회차를 지정해야만 응답하므로 먼저 알아내야 한다."""
    req = urllib.request.Request(LOTTO_REFERER, headers={"User-Agent": UA, "Referer": LOTTO_REFERER})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8")
    match = re.search(r'id="opt_val" value="(\d+)"', html)
    if not match:
        raise SystemExit("최신 회차 번호를 찾지 못했습니다. 동행복권 페이지 구조가 바뀌었을 수 있습니다.")
    return int(match.group(1))


def fetch_draws_after(last_round):
    """last_round 이후의 회차를 모두 받아온다.

    이 API는 지정한 회차부터 10회차씩 거슬러 내려주므로, 최신 회차에서 시작해
    필요한 구간을 다 채울 때까지 페이지를 넘긴다.
    """
    draws = {}
    cursor = fetch_latest_round()

    while cursor > last_round:
        url = f"{LOTTO_API}?srchDir=center&srchLtEpsd={cursor}"
        items = get_json(url, LOTTO_REFERER).get("data", {}).get("list", [])
        if not items:
            break

        page = [parse_draw(it) for it in items]
        for draw in page:
            if draw["round"] > last_round:
                draws[draw["round"]] = draw

        cursor = min(d["round"] for d in page) - 1

    return [draws[r] for r in sorted(draws)]


def load_rows():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def combo_key(row):
    nums = []
    for i in range(1, 5):
        raw = (row.get(f"no{i}") or "").strip()
        if raw:
            nums.append(int(float(raw)))
    return tuple(sorted(nums))


def update_lotto(dry_run):
    rows = load_rows()
    last_round = max(int(r["recentRound"]) for r in rows)
    print(f"로또 현재 데이터 최신 회차: {last_round}")

    new_draws = fetch_draws_after(last_round)
    if not new_draws:
        print("로또: 새로 반영할 회차가 없습니다.")
        return

    print(f"로또 새 회차 {len(new_draws)}개: {new_draws[0]['round']} ~ {new_draws[-1]['round']}")
    for d in new_draws:
        print(f"  제{d['round']}회 ({d['date']}) {d['numbers']}")

    if dry_run:
        print("(--dry-run: 로또 파일 수정 안 함)")
        return

    index = {combo_key(r): r for r in rows}

    for draw in new_draws:
        for size in (2, 3, 4):
            for combo in combinations(draw["numbers"], size):
                row = index.get(combo)
                if row is None:
                    row = {
                        "countType": str(size),
                        "count": "0",
                        "recentRound": "0",
                        "recentDate": "",
                        "no1": "",
                        "no2": "",
                        "no3": "",
                        "no4": "",
                    }
                    for i, n in enumerate(combo, start=1):
                        row[f"no{i}"] = str(n)
                    index[combo] = row
                    rows.append(row)

                row["count"] = str(int(row["count"]) + 1)
                # 이 조합이 '가장 최근에' 함께 나온 회차를 갱신
                if draw["round"] > int(row["recentRound"]):
                    row["recentRound"] = str(draw["round"])
                    row["recentDate"] = draw["date"]

    rows.sort(key=lambda r: (int(r["countType"]), -int(r["count"])))

    with open(CSV_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"로또 동반출현 데이터 갱신 완료 — 총 {len(rows)}행")


def update_pension(dry_run):
    """연금복권은 목요일 추첨이라 로또와 주기가 다르다.

    로또에 새 회차가 없어도 여기는 갱신될 수 있으므로 항상 따로 확인한다.
    회차 수가 적어 전체 목록을 받아 병합한다.
    """
    payload = get_json(PENSION_API, PENSION_REFERER)
    result = payload.get("data", {}).get("result", [])
    if not result:
        print("연금복권: 응답이 비어 있어 건너뜁니다.")
        return

    existing = json.loads(PENSION_PATH.read_text(encoding="utf-8"))
    old_max = max(int(r["psltEpsd"]) for r in existing["data"]["result"])
    new_max = max(int(r["psltEpsd"]) for r in result)

    if new_max <= old_max:
        print(f"연금복권: 이미 최신입니다 ({old_max}회)")
        return

    print(f"연금복권 새 회차: {old_max}회 -> {new_max}회")
    if dry_run:
        print("(--dry-run: 연금복권 파일 수정 안 함)")
        return

    merged = {int(r["psltEpsd"]): r for r in existing["data"]["result"]}
    merged.update({int(r["psltEpsd"]): r for r in result})
    existing["data"]["result"] = [merged[k] for k in sorted(merged)]
    PENSION_PATH.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
    print(f"연금복권 데이터 갱신 완료 ({new_max}회까지)")


def update_draw_history(dry_run):
    """회차별 원본 이력(로또_회차별_당첨번호.json)도 함께 채운다.

    분석 페이지가 이 파일을 쓴다. 동반출현 CSV는 조합 집계라서
    '몇 회차째 미출현' 같은 회차 단위 지표를 뽑을 수 없다.
    """
    if dry_run:
        print("(--dry-run: 회차 이력 파일 수정 안 함)")
        return

    import fetch_draws

    fetch_draws.main()


def main():
    dry_run = "--dry-run" in sys.argv
    update_lotto(dry_run)
    print()
    update_pension(dry_run)
    print()
    update_draw_history(dry_run)


if __name__ == "__main__":
    main()
