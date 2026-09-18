# -*- coding: utf-8 -*-
"""cURL -> 레시피 변환기 테스트.  실행: python test_curl_to_recipe.py

실제 주차 사이트의 cURL을 넣어보는 건 여기서 못 하지만, 크롬이 뱉는 형식 해석과
비밀번호가 결과 파일에 새지 않는지는 전부 여기서 막는다.
"""
import json
import os
import sys
import tempfile

from curl_to_recipe import (
    ParseError, body_to_dict, clean_headers, guess_entries_spec, looks_like_plate,
    main, mask_secrets, parse_curl, to_step,
)
from parking_watch import load_config, parse_entries, plate_matches

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


CHROME_LOGIN = """curl 'https://console.humax-parcs.com/store/login' \\
  -H 'accept: application/json' \\
  -H 'content-type: application/json' \\
  -H 'sec-ch-ua: "Chromium";v="124"' \\
  -H 'user-agent: Mozilla/5.0' \\
  -b 'JSESSIONID=abc123' \\
  --data-raw '{"loginId":"store01","password":"pw-secret"}'"""

CHROME_LIST = ("curl 'https://console.humax-parcs.com/store/api/inCars?size=50' "
               "-H 'accept: application/json'")

SAMPLE_RESPONSE = json.dumps({
    "code": "0000",
    "data": {"content": [
        {"inSeq": 101, "carNumber": "99허1111", "inDt": "2026-09-18 10:00", "dcYn": "N"},
        {"inSeq": 102, "carNumber": "12가3456", "inDt": "2026-09-18 10:05", "dcYn": "N"},
    ]},
}, ensure_ascii=False)


# ------------------------------------------------------------- cURL 해석

@case("크롬 Copy as cURL을 해석한다")
def _():
    got = parse_curl(CHROME_LOGIN)
    assert got["url"] == "https://console.humax-parcs.com/store/login", got
    assert got["method"] == "POST", got
    assert got["content_type"] == "json", got
    assert json.loads(got["body"])["loginId"] == "store01", got


@case("본문이 없으면 GET으로 본다")
def _():
    got = parse_curl(CHROME_LIST)
    assert got["method"] == "GET", got
    assert got["url"].endswith("?size=50"), got


@case("-X 로 준 메서드가 우선한다")
def _():
    assert parse_curl("curl 'https://x/y' -X PUT -d 'a=1'")["method"] == "PUT"


@case("남의 세션 쿠키(-b)는 버린다")
def _():
    step = to_step(parse_curl(CHROME_LOGIN), [])
    blob = json.dumps(step, ensure_ascii=False)
    assert "JSESSIONID" not in blob, blob


@case("브라우저 잡음 헤더를 걷어낸다")
def _():
    got = clean_headers({"sec-ch-ua": "x", "User-Agent": "y", "Content-Type": "json",
                         "Authorization": "Bearer t", "Accept": "application/json"})
    assert got == {"Authorization": "Bearer t", "Accept": "application/json"}, got


@case("여러 줄 cURL도 한 줄처럼 읽는다")
def _():
    assert parse_curl(CHROME_LOGIN)["url"].startswith("https://")


@case("curl이 아니면 거부한다")
def _():
    for bad in ("", "wget https://x", "curl 'unclosed"):
        try:
            parse_curl(bad)
        except ParseError:
            continue
        raise AssertionError("통과되면 안 됨: %r" % bad)


@case("폼 본문과 JSON 본문을 둘 다 dict로 만든다")
def _():
    assert body_to_dict("a=1&b=%ED%95%9C", "form") == {"a": "1", "b": "한"}
    assert body_to_dict('{"a":1}', "json") == {"a": 1}
    # 해석이 안 되는 본문은 통째로 _raw에 넣어 직접 고치게 둔다.
    assert body_to_dict("그냥문자열", "json") == {"_raw": "그냥문자열"}


# ------------------------------------------------------------- 비밀번호 가리기

@case("아이디와 비밀번호를 ${환경변수}로 바꾼다")
def _():
    secrets = [("pw-secret", "PARKING_PASS"), ("store01", "PARKING_USER")]
    step = to_step(parse_curl(CHROME_LOGIN), secrets)
    blob = json.dumps(step, ensure_ascii=False)
    assert "pw-secret" not in blob, blob
    assert "store01" not in blob, blob
    assert "${PARKING_PASS}" in blob and "${PARKING_USER}" in blob, blob


@case("중첩된 값 안의 비밀번호도 가린다")
def _():
    got = mask_secrets({"a": {"b": ["x-pw-x"]}}, [("pw", "PARKING_PASS")])
    assert got == {"a": {"b": ["x-${PARKING_PASS}-x"]}}, got


@case("비밀번호가 결과 어딘가에 남으면 파일을 만들지 않는다")
def _():
    # 치환은 요청 단계에만 걸리므로, 치환이 닿지 않는 자리(plates)에 같은 값을 넣어
    # 마지막 안전장치가 실제로 막는지 본다.
    with tempfile.TemporaryDirectory() as d:
        curl = os.path.join(d, "c.txt")
        out = os.path.join(d, "out.json")
        with open(curl, "w", encoding="utf-8") as f:
            f.write("curl 'https://x/api' --data-raw 'a=1'")
        rc = main(["--entries", curl, "--register", curl,
                   "--plate", "pw-secret", "--password", "pw-secret", "-o", out])
        assert rc == 1, rc
        assert not os.path.exists(out), "비밀번호가 남았는데 파일이 생겼다"


@case("평범한 경우엔 비밀번호가 결과에 안 남는다")
def _():
    with tempfile.TemporaryDirectory() as d:
        login = os.path.join(d, "login.txt")
        api = os.path.join(d, "api.txt")
        out = os.path.join(d, "out.json")
        with open(login, "w", encoding="utf-8") as f:
            f.write(CHROME_LOGIN)
        with open(api, "w", encoding="utf-8") as f:
            f.write(CHROME_LIST)
        rc = main(["--login", login, "--entries", api, "--register", api,
                   "--plate", "12가3456", "--user", "store01", "--password", "pw-secret", "-o", out])
        assert rc == 0, rc
        blob = open(out, encoding="utf-8").read()
        assert "pw-secret" not in blob and "store01" not in blob, blob


# ------------------------------------------------------------- 응답 구조 추측

@case("응답에서 배열 위치와 차량번호 키를 찾는다")
def _():
    spec = guess_entries_spec(json.loads(SAMPLE_RESPONSE))
    assert spec["list_path"] == "data.content", spec
    assert spec["fields"]["plate"] == "carNumber", spec
    assert spec["fields"]["id"] == "inSeq", spec
    assert spec["fields"]["entered_at"] == "inDt", spec
    assert spec["_already_when_후보"]["field"] == "dcYn", spec


@case("추측한 구조로 실제 파싱이 된다")
def _():
    spec = guess_entries_spec(json.loads(SAMPLE_RESPONSE))
    spec.pop("_already_when_후보", None)
    entries = parse_entries(SAMPLE_RESPONSE, spec)
    assert [e["plate"] for e in entries] == ["99허1111", "12가3456"], entries
    mine = [e for e in entries if plate_matches(e["plate"], ["12가3456"])]
    assert len(mine) == 1 and mine[0]["id"] == 102, mine


@case("최상위가 배열인 응답도 찾는다")
def _():
    spec = guess_entries_spec([{"no": 1, "car": "12가3456"}])
    assert "list_path" not in spec, spec
    assert spec["fields"]["plate"] == "car", spec


@case("차량번호가 없으면 추측하지 않는다")
def _():
    assert guess_entries_spec({"data": {"total": 0, "content": []}}) is None
    assert guess_entries_spec({"msg": "권한 없음"}) is None


@case("여러 형식의 차량번호를 알아본다")
def _():
    for good in ("12가3456", "123가4567", "서울12가3456", "12가34**"):
        assert looks_like_plate(good), good
    for bad in ("2026-09-18", "0000", "N", "", "abc"):
        assert not looks_like_plate(bad), bad


# ------------------------------------------------------------- 전체 조립

@case("만들어진 레시피는 parking_watch가 읽을 수 있다")
def _():
    with tempfile.TemporaryDirectory() as d:
        paths = {}
        for name, text in (("login", CHROME_LOGIN), ("entries", CHROME_LIST),
                           ("register", "curl 'https://console.humax-parcs.com/store/api/discount' "
                                        "-H 'content-type: application/json' "
                                        "--data-raw '{\"inSeq\":102,\"carNumber\":\"12가3456\"}'")):
            paths[name] = os.path.join(d, name + ".txt")
            with open(paths[name], "w", encoding="utf-8") as f:
                f.write(text)
        resp = os.path.join(d, "resp.json")
        with open(resp, "w", encoding="utf-8") as f:
            f.write(SAMPLE_RESPONSE)
        out = os.path.join(d, "parking_site.json")

        rc = main(["--login", paths["login"], "--entries", paths["entries"],
                   "--register", paths["register"], "--entries-response", resp,
                   "--plate", "12가3456", "--user", "store01", "--password", "pw-secret",
                   "--sample-id", "102", "-o", out])
        assert rc == 0, rc

        cfg = load_config(out)
        assert cfg["plates"] == ["12가3456"], cfg
        assert cfg["entries"]["list_path"] == "data.content", cfg
        assert cfg["register"]["body"]["inSeq"] == "${entry.id}", cfg["register"]
        assert cfg["register"]["body"]["carNumber"] == "${entry.plate}", cfg["register"]
        blob = json.dumps(cfg, ensure_ascii=False)
        assert "pw-secret" not in blob and "store01" not in blob, blob


if __name__ == "__main__":
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("  PASS  %s" % name)
        except Exception as e:
            failed += 1
            print("  FAIL  %s -> %s: %s" % (name, type(e).__name__, e))
    print("\n%d passed, %d failed" % (len(CASES) - failed, failed))
    sys.exit(1 if failed else 0)
