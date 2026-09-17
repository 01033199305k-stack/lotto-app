# -*- coding: utf-8 -*-
"""자동 무료주차 등록 테스트.  실행: python test_parking_watch.py

실제 주차등록 사이트 없이 돌려야 하므로, 로그인·입차목록·무료등록을 흉내내는
가짜 서버를 띄우고 그걸 상대로 검증한다.  진짜 사이트의 화면 구조가 바뀌는 건
여기서 못 잡지만, 레시피 해석·차량번호 대조·중복 등록 방지는 전부 여기서 막는다.
"""
import json
import os
import re
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from parking_watch import (
    ConfigError, State, StepError, already_registered, dig, entry_key,
    load_config, normalize_plate, parse_entries, plate_matches, render, run_once,
)

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


# ------------------------------------------------------------- 가짜 주차 사이트

class FakeSite:
    """/login -> 쿠키 발급, /list -> 입차 목록, /register -> 할인 적용."""

    def __init__(self):
        self.entries = []
        self.registered = []
        self.require_login = True
        self.list_format = "json"


SITE = FakeSite()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 테스트 출력이 지저분해지지 않게 액세스 로그를 끈다.

    def _send(self, code, body, headers=None):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _logged_in(self):
        return not SITE.require_login or "sid=ok" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            return self._send(200, '<form><input name="_csrf" value="TOKEN-123"></form>')
        if path == "/list":
            if not self._logged_in():
                return self._send(200, "로그인이 필요합니다")
            if SITE.list_format == "html":
                rows = "".join(
                    '<tr><td>%s</td><td><a href="/register?seq=%s">등록</a></td></tr>'
                    % (e["carNo"], e["inSeq"]) for e in SITE.entries)
                return self._send(200, "<table>%s</table>" % rows)
            return self._send(200, json.dumps({"data": {"list": SITE.entries}}, ensure_ascii=False))
        return self._send(404, "no")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

        if path == "/login":
            if form.get("_csrf") != "TOKEN-123":
                return self._send(200, "잘못된 요청입니다")
            if form.get("userId") != "me" or form.get("userPw") != "pw!":
                return self._send(200, "비밀번호가 일치하지 않습니다")
            return self._send(200, "환영합니다", {"Set-Cookie": "sid=ok; Path=/"})

        if path == "/register":
            if not self._logged_in():
                return self._send(200, '{"resultCode":"9999"}')
            body = json.loads(raw) if raw.startswith("{") else form
            SITE.registered.append(body)
            for e in SITE.entries:
                if str(e["inSeq"]) == str(body.get("inSeq")):
                    e["dcYn"] = "Y"
            return self._send(200, '{"resultCode":"0000"}')

        return self._send(404, "no")


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


SERVER = start_server()
BASE = "http://127.0.0.1:%d" % SERVER.server_address[1]


def reset(entries=None, list_format="json"):
    SITE.entries = entries if entries is not None else [
        {"carNo": "99허1111", "inSeq": 1, "inDtm": "2026-09-17 10:00", "dcYn": "N"},
        {"carNo": "12가3456", "inSeq": 2, "inDtm": "2026-09-17 10:05", "dcYn": "N"},
    ]
    SITE.registered = []
    SITE.require_login = True
    SITE.list_format = list_format
    os.environ["PARKING_USER"] = "me"
    os.environ["PARKING_PASS"] = "pw!"


def config(**over):
    cfg = {
        "plates": ["12가3456"],
        "login": {
            "prepare": {"url": BASE + "/login", "extract": {"csrf": 'value="([^"]+)"'}},
            "url": BASE + "/login",
            "method": "POST",
            "body": {"userId": "${PARKING_USER}", "userPw": "${PARKING_PASS}", "_csrf": "${csrf}"},
            "failure_contains": "비밀번호가 일치하지",
        },
        "entries": {
            "url": BASE + "/list",
            "format": "json",
            "list_path": "data.list",
            "fields": {"plate": "carNo", "id": "inSeq", "entered_at": "inDtm", "discount": "dcYn"},
            "already_when": {"field": "discount", "equals": ["Y"]},
        },
        "register": {
            "url": BASE + "/register",
            "method": "POST",
            "content_type": "json",
            "body": {"inSeq": "${entry.id}", "carNo": "${entry.plate}"},
            "success_contains": '"resultCode":"0000"',
        },
    }
    cfg.update(over)
    return cfg


# ------------------------------------------------------------- 전체 흐름

@case("내 차가 입차해 있으면 무료등록을 호출한다")
def _():
    reset()
    assert run_once(config(), commit=True) == 1
    assert SITE.registered == [{"inSeq": "2", "carNo": "12가3456"}], SITE.registered


@case("--commit 없이는 등록하지 않는다")
def _():
    reset()
    assert run_once(config(), commit=False) == 0
    assert SITE.registered == [], SITE.registered


@case("내 차가 없으면 아무것도 하지 않는다")
def _():
    reset([{"carNo": "77바8888", "inSeq": 9, "inDtm": "-", "dcYn": "N"}])
    assert run_once(config(), commit=True) == 0
    assert SITE.registered == []


@case("사이트가 이미 할인 적용됨으로 표시하면 다시 등록하지 않는다")
def _():
    reset([{"carNo": "12가3456", "inSeq": 2, "inDtm": "-", "dcYn": "Y"}])
    assert run_once(config(), commit=True) == 0
    assert SITE.registered == []


@case("같은 입차 건은 두 번 등록하지 않는다 (기록 파일)")
def _():
    reset()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "state.json")
        assert run_once(config(), commit=True, state_path=path) == 1
        # 사이트가 할인 표시를 안 해주는 상황을 만들어도 기록이 막아야 한다.
        for e in SITE.entries:
            e["dcYn"] = "N"
        assert run_once(config(), commit=True, state_path=path) == 0
    assert len(SITE.registered) == 1, SITE.registered


@case("차가 두 대면 두 대 다 등록한다")
def _():
    reset([
        {"carNo": "12가3456", "inSeq": 2, "inDtm": "-", "dcYn": "N"},
        {"carNo": "34나7890", "inSeq": 3, "inDtm": "-", "dcYn": "N"},
    ])
    cfg = config()
    cfg["plates"] = ["12가3456", "34나7890"]
    assert run_once(cfg, commit=True) == 2
    assert len(SITE.registered) == 2


@case("로그인 세션(쿠키)이 목록·등록 요청까지 이어진다")
def _():
    reset()
    run_once(config(), commit=True)
    assert SITE.registered, "쿠키가 안 붙었으면 목록이 비어서 등록도 없다"


@case("비밀번호가 틀리면 실패로 알려준다")
def _():
    reset()
    os.environ["PARKING_PASS"] = "wrong"
    try:
        run_once(config(), commit=True)
    except StepError:
        return
    raise AssertionError("로그인 실패를 못 잡았다")


@case("HTML 목록도 row_regex로 읽는다")
def _():
    reset(list_format="html")
    cfg = config()
    cfg["entries"] = {
        "url": BASE + "/list",
        "format": "html",
        "row_regex": r"<tr><td>(?P<plate>[^<]+)</td>.*?seq=(?P<id>\d+)",
    }
    assert run_once(cfg, commit=True) == 1
    assert SITE.registered == [{"inSeq": "2", "carNo": "12가3456"}], SITE.registered


@case("사이트가 죽어 있으면 StepError로 끝난다")
def _():
    reset()
    cfg = config()
    cfg["entries"]["url"] = "http://127.0.0.1:1/list"
    cfg["retries"] = 0
    try:
        run_once(cfg, commit=True)
    except StepError:
        return
    raise AssertionError("연결 실패를 못 잡았다")


# ------------------------------------------------------------- 차량번호 대조

@case("공백과 하이픈은 무시하고 대조한다")
def _():
    assert plate_matches("12가 3456", ["12-가-3456"])
    assert plate_matches("서울12가3456", ["서울 12가 3456"])


@case("사이트가 가린 번호(12가34**)도 맞춘다")
def _():
    assert plate_matches("12가34**", ["12가3456"], "masked")
    assert not plate_matches("12가34**", ["12가9956"], "masked")


@case("exact 모드는 가린 번호를 맞다고 하지 않는다")
def _():
    assert not plate_matches("12가34**", ["12가3456"], "exact")


@case("다른 차는 맞다고 하지 않는다")
def _():
    assert not plate_matches("99허1111", ["12가3456"])
    assert not plate_matches("", ["12가3456"])
    assert not plate_matches(None, ["12가3456"])


@case("tail4 모드는 뒤 4자리만 본다")
def _():
    assert plate_matches("서울99허3456", ["12가3456"], "tail4")
    assert not plate_matches("서울99허3457", ["12가3456"], "tail4")


@case("normalize_plate는 마스킹 문자를 남긴다")
def _():
    assert normalize_plate(" 12가-34** ") == "12가34**"


# ------------------------------------------------------------- 레시피 해석

@case("${환경변수}와 ${ctx} 값을 채운다")
def _():
    os.environ["TEST_PW"] = "secret"
    got = render({"a": "${TEST_PW}", "b": ["${entry.id}"]}, {"entry.id": 7})
    assert got == {"a": "secret", "b": ["7"]}, got


@case("채울 값이 없으면 설정 오류로 알려준다")
def _():
    os.environ.pop("NO_SUCH_VAR", None)
    try:
        render("${NO_SUCH_VAR}", {})
    except ConfigError:
        return
    raise AssertionError("없는 환경변수를 그냥 넘겼다")


@case("dig는 점 경로를 따라간다")
def _():
    obj = {"data": {"list": [{"carNo": "12가3456"}]}}
    assert dig(obj, "data.list") == [{"carNo": "12가3456"}]
    assert dig(obj, "data.list.0.carNo") == "12가3456"
    assert dig(obj, "data.nope") is None


@case("list_path가 틀리면 어디가 틀렸는지 알려준다")
def _():
    try:
        parse_entries('{"data":{}}', {"list_path": "data.list", "fields": {"plate": "carNo"}})
    except StepError as e:
        assert "list_path" in str(e), e
        return
    raise AssertionError("잘못된 list_path를 통과시켰다")


@case("JSON이 아닌 응답에 format 힌트를 준다")
def _():
    try:
        parse_entries("<html>로그인</html>", {"list_path": "list", "fields": {"plate": "carNo"}})
    except StepError as e:
        assert "html" in str(e), e
        return
    raise AssertionError("HTML 응답을 JSON으로 통과시켰다")


@case("row_regex에 plate 그룹이 없으면 거부한다")
def _():
    try:
        parse_entries("<tr>", {"format": "html", "row_regex": r"<tr>"})
    except ConfigError:
        return
    raise AssertionError("plate 그룹 없는 정규식을 통과시켰다")


@case("차량번호가 빠진 레시피를 거부한다")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "c.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"plates": [], "entries": {}, "register": {}}, f)
        try:
            load_config(path)
        except ConfigError as e:
            assert "plates" in str(e), e
            return
    raise AssertionError("빈 plates를 통과시켰다")


@case("already_when은 equals와 contains를 다 받는다")
def _():
    assert already_registered({"discount": "Y"}, {"already_when": {"field": "discount", "equals": ["Y"]}})
    assert already_registered({"raw": "등록완료"}, {"already_when": {"field": "raw", "contains": "등록완료"}})
    assert not already_registered({"discount": "N"}, {"already_when": {"field": "discount", "equals": ["Y"]}})
    assert not already_registered({"discount": "N"}, {})


@case("입차 id가 없으면 차량번호+시각으로 구분한다")
def _():
    assert entry_key({"id": 5, "plate": "12가3456"}) == "5"
    assert entry_key({"plate": "12가 3456", "entered_at": "10:05"}) == "12가3456|10:05"


@case("오래된 기록은 저장할 때 정리된다")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"done": {"old": "2020-01-01T00:00:00+00:00"}}, f)
        s = State(path, keep_hours=24)
        s.mark("new")
        s.save()
        assert State(path).seen("new")
        assert not State(path).seen("old")


@case("깨진 기록 파일은 빈 상태로 넘어간다")
def _():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        assert State(path).done == {}


@case("예시 레시피는 항상 읽히는 상태로 둔다")
def _():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "parking_site.example.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    for key in ("plates", "entries", "register"):
        assert key in cfg, key
    # 비밀번호가 실수로 박제되지 않았는지 본다.
    blob = json.dumps(cfg, ensure_ascii=False)
    for secret in ("PARKING_USER", "PARKING_PASS"):
        assert "${%s}" % secret in blob, secret
    assert not re.search(r'"userPw"\s*:\s*"(?!\$\{)', blob), "비밀번호가 그대로 들어있다"


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
