# -*- coding: utf-8 -*-
"""브라우저 기록 -> 레시피 -> 실제 등록까지 한 바퀴 돌려보는 테스트.

실행: python test_capture_requests.py   (playwright와 chromium이 있어야 한다)

진짜 주차등록 사이트를 흉내낸 가짜 콘솔(로그인 화면 + 입차목록 + 무료등록 버튼)을
띄우고, 크로미움으로 사람이 하듯 클릭해서 요청을 기록한 뒤, 그걸로 만든 레시피가
정말로 무료등록을 호출하는지까지 확인한다.
"""
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CARS = []
REGISTERED = []

LOGIN_PAGE = """<!doctype html><meta charset="utf-8"><title>매장 콘솔</title>
<form id="f"><input id="loginId" value=""><input id="password" type="password" value="">
<button type="submit">로그인</button></form>
<script>
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch('/store/api/login', {method:'POST',
    headers:{'content-type':'application/json'},
    body: JSON.stringify({loginId: loginId.value, password: password.value})});
  if ((await r.json()).resultCode === '0000') location.href = '/store/cars';
};
</script>"""

CARS_PAGE = """<!doctype html><meta charset="utf-8"><title>입차 차량</title>
<table id="t"></table>
<script>
async function load() {
  const r = await fetch('/store/api/inCars?size=50');
  const rows = (await r.json()).data.content;
  t.innerHTML = rows.map(c =>
    `<tr><td>${c.carNumber}</td><td><button class="reg" data-seq="${c.inSeq}" data-car="${c.carNumber}">무료등록</button></td></tr>`).join('');
  document.querySelectorAll('.reg').forEach(b => b.onclick = async () => {
    await fetch('/store/api/discount', {method:'POST',
      headers:{'content-type':'application/json'},
      body: JSON.stringify({inSeq: Number(b.dataset.seq), carNumber: b.dataset.car, dcCode:'FREE'})});
    load();
  });
}
load();
</script>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _authed(self):
        return "sid=ok" in (self.headers.get("Cookie") or "")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/store", "/store/"):
            return self._send(200, LOGIN_PAGE)
        if path == "/store/cars":
            return self._send(200, CARS_PAGE)
        if path == "/store/api/inCars":
            if not self._authed():
                return self._send(401, '{"resultCode":"9401"}', "application/json; charset=utf-8")
            return self._send(200, json.dumps({"resultCode": "0000", "data": {"content": CARS}},
                                              ensure_ascii=False), "application/json; charset=utf-8")
        return self._send(404, "no")

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8")
        body = json.loads(raw) if raw.startswith("{") else {}

        if path == "/store/api/login":
            if body.get("loginId") == "store01" and body.get("password") == "pw-secret":
                return self._send(200, '{"resultCode":"0000"}', "application/json; charset=utf-8",
                                  {"Set-Cookie": "sid=ok; Path=/"})
            return self._send(200, '{"resultCode":"9001"}', "application/json; charset=utf-8")

        if path == "/store/api/discount":
            if not self._authed():
                return self._send(401, '{"resultCode":"9401"}', "application/json; charset=utf-8")
            REGISTERED.append(body)
            for car in CARS:
                if car["inSeq"] == body.get("inSeq"):
                    car["dcYn"] = "Y"
            return self._send(200, '{"resultCode":"0000","message":"등록되었습니다"}',
                              "application/json; charset=utf-8")
        return self._send(404, "no")


def reset():
    del CARS[:], REGISTERED[:]
    CARS.extend([
        {"inSeq": 101, "carNumber": "99허1111", "inDt": "2026-09-18 10:00", "dcYn": "N"},
        {"inSeq": 102, "carNumber": "12가3456", "inDt": "2026-09-18 10:05", "dcYn": "N"},
        {"inSeq": 103, "carNumber": "34나7890", "inDt": "2026-09-18 10:07", "dcYn": "N"},
    ])


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("SKIP: playwright가 없어요 (pip install playwright)")
        return 0

    from capture_requests import attach, build_recipe, launch_browser
    from parking_watch import run_once

    reset()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    records = []
    print("가짜 콘솔을 크로미움으로 조작합니다: %s/store" % base)
    with sync_playwright() as pw:
        try:
            browser = launch_browser(pw, headless=True)
        except Exception as e:
            print("SKIP: 크로미움을 못 띄웠어요 -> %s" % e)
            return 0
        page = browser.new_page()
        attach(page, records)
        page.goto(base + "/store")
        page.fill("#loginId", "store01")
        page.fill("#password", "pw-secret")
        page.click("button[type=submit]")          # 로그인
        page.wait_for_selector(".reg")             # 입차 목록 로딩
        page.click("tr:nth-child(1) .reg")         # 남의 차 하나 무료등록 (사람이 하듯)
        page.wait_for_timeout(400)
        browser.close()

    print("요청 %d개 기록" % len(records))
    recipe = build_recipe(records, plate="12가3456", user="store01", password="pw-secret")
    print(json.dumps(recipe, ensure_ascii=False, indent=2))

    failed = 0

    def check(name, cond):
        nonlocal failed
        print(("  PASS  " if cond else "  FAIL  ") + name)
        if not cond:
            failed += 1

    blob = json.dumps(recipe, ensure_ascii=False)
    check("로그인 요청을 골라냈다", recipe.get("login", {}).get("url", "").endswith("/store/api/login"))
    check("비밀번호를 자리표시자로 바꿨다", "pw-secret" not in blob and "${PARKING_PASS}" in blob)
    check("아이디를 자리표시자로 바꿨다", "store01" not in blob and "${PARKING_USER}" in blob)
    check("입차 목록 요청을 골라냈다", "/store/api/inCars" in recipe["entries"]["url"])
    check("배열 위치를 찾았다", recipe["entries"].get("list_path") == "data.content")
    check("차량번호 키를 찾았다", recipe["entries"]["fields"].get("plate") == "carNumber")
    check("입차 식별자 키를 찾았다", recipe["entries"]["fields"].get("id") == "inSeq")
    check("할인 표시를 fields와 already_when에 같이 넣었다",
          recipe["entries"]["fields"].get("discount") == "dcYn" and
          recipe["entries"].get("already_when", {}).get("field") == "discount")
    check("무료등록 요청을 골라냈다", recipe.get("register", {}).get("url", "").endswith("/store/api/discount"))
    check("등록 본문의 입차 식별자를 ${entry.id}로 바꿨다",
          recipe["register"].get("body", {}).get("inSeq") == "${entry.id}")
    check("등록 본문의 차량번호를 ${entry.plate}로 바꿨다",
          recipe["register"]["body"].get("carNumber") == "${entry.plate}")
    check("성공 판정 문자열을 찾았다", "success_contains" in recipe["register"])

    # 여기까지가 '사람이 클릭한 걸 받아적은 결과'다. 이제 그 레시피로 진짜 돌려본다.
    import os
    os.environ["PARKING_USER"] = "store01"
    os.environ["PARKING_PASS"] = "pw-secret"
    reset()

    import tempfile
    state = os.path.join(tempfile.mkdtemp(), "state.json")
    recipe.pop("state_file", None)

    print("\n만들어진 레시피로 미리보기:")
    check("미리보기는 등록하지 않는다",
          run_once(recipe, commit=False, state_path=state) == 0 and not REGISTERED)

    print("\n만들어진 레시피로 실제 등록:")
    check("내 차 한 대를 등록했다", run_once(recipe, commit=True, state_path=state) == 1)
    check("등록된 게 내 차가 맞다 (식별자가 숫자 그대로 나갔다)",
          len(REGISTERED) == 1 and REGISTERED[0].get("inSeq") == 102)
    # 기록 파일을 지워도, 사이트가 dcYn=Y로 바뀐 걸 보고 다시 등록하지 않아야 한다.
    os.remove(state)
    check("기록이 없어도 사이트 표시(already_when)가 중복 등록을 막는다",
          run_once(recipe, commit=True, state_path=state) == 0 and len(REGISTERED) == 1)

    print("\n%d failed" % failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
