"""로또 회차별 당첨번호 전체 이력을 수집한다.

`동반출현_전체데이터.csv`는 조합별 집계라서 "몇 회차째 안 나왔는지",
"홀짝 비율이 어떻게 분포하는지" 같은 회차 단위 분석을 할 수 없다.
그 원본이 되는 파일을 따로 둔다.

사용법:
    python fetch_draws.py            # 없는 회차만 채움
    python fetch_draws.py --rebuild  # 1회차부터 전부 다시 수집

update_data.py가 매주 이 스크립트를 호출하므로 평소에는 직접 쓸 일이 없다.
"""

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
DRAWS_PATH = BASE / "로또_회차별_당첨번호.json"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
REFERER = "https://www.dhlottery.co.kr/lt645/result"
API = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"

# 목록 API가 한 번에 내려주는 회차 수. 커서를 이만큼씩 건너뛴다.
PAGE_SIZE = 10
# 연속 호출 사이 간격(초). 동행복권 쪽에 몰아치지 않도록 둔다.
DELAY = 0.25


def get_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": REFERER, "X-Requested-With": "XMLHttpRequest"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_round():
    req = urllib.request.Request(REFERER, headers={"User-Agent": UA, "Referer": REFERER})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8")
    m = re.search(r'id="opt_val" value="(\d+)"', html)
    if not m:
        raise SystemExit("최신 회차를 찾지 못했습니다. 페이지 구조가 바뀌었을 수 있습니다.")
    return int(m.group(1))


def parse(item):
    return {
        "round": item["ltEpsd"],
        "date": item["ltRflYmd"],
        "numbers": sorted(item[f"tm{i}WnNo"] for i in range(1, 7)),
        "bonus": item["bnsWnNo"],
    }


def load_existing():
    if not DRAWS_PATH.exists():
        return {}
    data = json.loads(DRAWS_PATH.read_text(encoding="utf-8"))
    return {d["round"]: d for d in data.get("draws", [])}


def main():
    rebuild = "--rebuild" in sys.argv
    existing = {} if rebuild else load_existing()
    newest = latest_round()

    have = set(existing)
    want = set(range(1, newest + 1))
    missing = want - have

    if not missing:
        print(f"이미 최신입니다 ({newest}회, {len(existing)}개 보유)")
        return

    print(f"최신 {newest}회 / 보유 {len(have)}개 / 수집 대상 {len(missing)}개")

    # 커서를 위에서부터 내리며 페이지를 받는다. 응답이 요청 회차 주변을 함께
    # 주므로 이미 가진 회차가 섞여 와도 그냥 덮어쓰면 된다.
    cursor = max(missing)
    fetched = 0
    while cursor >= 1 and (set(range(1, newest + 1)) - set(existing)):
        items = get_json(f"{API}?srchDir=center&srchLtEpsd={cursor}").get("data", {}).get("list", [])
        if not items:
            break

        page = [parse(it) for it in items]
        for draw in page:
            existing[draw["round"]] = draw
        fetched += len(page)

        lowest = min(d["round"] for d in page)
        if lowest <= 1:
            break
        cursor = lowest - 1

        if fetched % 200 < PAGE_SIZE:
            print(f"  ... {fetched}건 수집, 현재 커서 {cursor}")
        time.sleep(DELAY)

    draws = [existing[r] for r in sorted(existing)]
    DRAWS_PATH.write_text(
        json.dumps({"latest": max(existing), "draws": draws}, ensure_ascii=False),
        encoding="utf-8",
    )
    gaps = sorted(set(range(1, max(existing) + 1)) - set(existing))
    print(f"저장 완료 — {len(draws)}회차 (1 ~ {max(existing)})")
    if gaps:
        print(f"주의: 빠진 회차 {len(gaps)}개 — 예: {gaps[:10]}")


if __name__ == "__main__":
    main()
