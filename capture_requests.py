# -*- coding: utf-8 -*-
"""브라우저를 띄워 주차등록 사이트의 요청을 받아적고, 레시피를 자동으로 만든다.

개발자도구를 직접 만질 필요 없이, 평소 하던 대로 로그인하고 무료등록을 한 번만
누르면 된다. 그 사이 오간 요청을 전부 기록해서 로그인/입차목록/무료등록 세 개를
골라내고 parking_site.json을 뱉는다.

    pip install playwright && playwright install chromium
    python capture_requests.py --plate '12가3456'

비밀번호는 브라우저에 직접 입력하면 되고(이 스크립트는 받지 않아도 된다), 넘기더라도
결과 파일에는 ${PARKING_PASS} 자리표시자만 남는다.
"""
import argparse
import json
import os
import re
import sys

from curl_to_recipe import (
    body_to_dict, clean_headers, guess_entries_spec, looks_like_plate,
    mask_secrets, sample_ids, to_step,
)

DEFAULT_URL = "https://console.humax-parcs.com/store"
PASSWORD_KEY_RE = re.compile(r"pass|pwd|\bpw\b", re.I)
RESULT_KEYS = ("resultCode", "result_code", "code", "result", "status", "success", "msg", "message")


class Record:
    """오간 요청 하나. 응답 본문까지 같이 들고 있어야 구조를 추측할 수 있다."""

    def __init__(self, request):
        self.url = request.url
        self.method = request.method
        self.headers = dict(request.headers)
        self.post_data = request.post_data
        self.response_text = None
        self.order = None

    @property
    def content_type(self):
        for name, value in self.headers.items():
            if name.lower() == "content-type" and "json" in value.lower():
                return "json"
        if self.post_data and self.post_data.lstrip().startswith(("{", "[")):
            return "json"
        return "form"

    def as_curl_dict(self):
        return {"url": self.url, "method": self.method, "headers": self.headers,
                "body": self.post_data, "content_type": self.content_type}

    def json(self):
        if not self.response_text:
            return None
        try:
            return json.loads(self.response_text)
        except ValueError:
            return None


def launch_browser(pw, headless=False):
    """크로미움을 띄운다. 평범한 PC에서는 첫 줄로 끝나고, 아래는 컨테이너용 보정이다.

    root로 돌면 샌드박스를 꺼야 뜨고, playwright 버전과 미리 깔린 크로미움 버전이
    어긋나면 실행 파일 경로를 직접 짚어줘야 한다.
    """
    args = ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []
    try:
        return pw.chromium.launch(headless=headless, args=args)
    except Exception:
        fallback = os.environ.get("CHROMIUM_PATH") or "/opt/pw-browsers/chromium"
        if not os.path.exists(fallback):
            raise
        return pw.chromium.launch(headless=headless, args=args, executable_path=fallback)


def attach(page, records):
    """page에서 오가는 XHR/fetch를 records에 쌓는다."""
    def on_response(response):
        request = response.request
        if request.resource_type not in ("xhr", "fetch", "document"):
            return
        record = Record(request)
        record.order = len(records)
        try:
            # 이미지·파일 응답은 텍스트로 읽으면 터진다. 조용히 넘긴다.
            record.response_text = response.text()
        except Exception:
            pass
        records.append(record)

    page.on("response", on_response)


# ---------------------------------------------------------------- 고르기

def pick_entries(records):
    """응답에 차량번호처럼 생긴 값이 가장 많이 들어있는 요청이 입차 목록이다."""
    best = None
    for record in records:
        payload = record.json()
        if payload is None:
            continue
        spec = guess_entries_spec(payload)
        if not spec:
            continue
        rows = len(re.findall(r"[0-9]{2,3}[가-힣][0-9*]{4}", record.response_text or ""))
        if best is None or rows > best[0]:
            best = (rows, record, spec)
    return (best[1], best[2]) if best else (None, None)


def pick_login(records, password=None):
    """비밀번호가 실린 POST. 값을 모르면 비밀번호처럼 생긴 필드 이름으로 찾는다."""
    for record in records:
        if record.method != "POST" or not record.post_data:
            continue
        if password and password in record.post_data:
            return record
    for record in records:
        if record.method != "POST" or not record.post_data:
            continue
        body = body_to_dict(record.post_data, record.content_type) or {}
        if any(PASSWORD_KEY_RE.search(k) for k in body):
            return record
    return None


def pick_register(records, entries_record, known_ids, login_record):
    """입차 목록을 본 뒤에 나간 POST 중, 목록의 값을 실어 보낸 것이 무료등록이다."""
    after = entries_record.order if entries_record else -1
    best = None
    for record in records:
        if record is login_record or record.method not in ("POST", "PUT", "PATCH"):
            continue
        if record.order <= after or not record.post_data:
            continue
        body = body_to_dict(record.post_data, record.content_type) or {}
        hit = any(str(v) in known_ids for v in body.values()) or \
              any(looks_like_plate(str(v)) for v in body.values())
        # 목록 값을 실어 보낸 게 확실하면 그걸 쓰고, 없으면 마지막 POST를 후보로 둔다.
        if hit:
            best = (2, record)
        elif best is None or best[0] < 1:
            best = (1, record)
    return best[1] if best else None


def guess_success_contains(record):
    """등록 성공 응답에서만 나오는 짧은 표식을 찾아 success_contains 후보로 준다."""
    payload = record.json() if record else None
    if isinstance(payload, dict):
        for key in RESULT_KEYS:
            if key in payload and isinstance(payload[key], (str, int, bool)):
                return '"%s":%s' % (key, json.dumps(payload[key], ensure_ascii=False))
    if record and record.response_text:
        for word in ("성공", "완료", "등록되었습니다"):
            if word in record.response_text:
                return word
    return None


# ---------------------------------------------------------------- 조립

def build_recipe(records, plate=None, user=None, password=None):
    """기록한 요청들 -> parking_watch 레시피. 못 고른 자리는 _할일로 표시해 둔다."""
    secrets = []
    if password:
        secrets.append((password, "PARKING_PASS"))
    if user:
        secrets.append((user, "PARKING_USER"))

    entries_record, entries_spec = pick_entries(records)
    if entries_record is None:
        raise SystemExit("입차 목록으로 보이는 요청을 못 찾았어요. 목록 화면을 새로고침한 뒤 다시 해보세요.")

    login_record = pick_login(records, password)
    known_ids = sample_ids(entries_record.json(), entries_spec) if entries_spec else set()
    register_record = pick_register(records, entries_record, known_ids, login_record)

    recipe = {
        "_설명": "capture_requests.py가 브라우저 기록에서 만든 초안. --commit 전에 미리보기로 확인하세요.",
        "plates": [plate] if plate else ["여기에 내 차량번호"],
        "plate_match": "masked",
        "state_file": ".parking_state.json",
    }

    if login_record:
        recipe["login"] = to_step(login_record.as_curl_dict(), secrets)

    entries = to_step(entries_record.as_curl_dict(), secrets)
    entries.pop("body", None)  # 목록은 GET 쿼리스트링이 url에 이미 들어 있다.
    entries.update(entries_spec)
    already = entries.pop("_already_when_후보", None)
    if already:
        entries["already_when"] = already
    recipe["entries"] = entries

    if register_record:
        register = to_step(register_record.as_curl_dict(), secrets)
        body = register.get("body")
        if isinstance(body, dict):
            for key, value in list(body.items()):
                if looks_like_plate(str(value)):
                    body[key] = "${entry.plate}"
                elif str(value) in known_ids:
                    body[key] = "${entry.id}"
        success = guess_success_contains(register_record)
        if success:
            register["success_contains"] = success
        else:
            register["_할일"] = "성공 응답에만 있는 문자열을 success_contains에 넣으세요."
        recipe["register"] = register
    else:
        recipe["register"] = {"_할일": "무료등록 요청을 못 골랐어요. 등록 버튼을 한 번 누른 뒤 다시 기록하세요."}

    # 헤더 토큰을 쓰는 사이트라면 쿠키만으로는 목록이 안 나온다. 미리 알려준다.
    if any(k.lower() == "authorization" for k in entries_record.headers):
        recipe["_주의"] = ("목록 요청이 Authorization 헤더를 씁니다. 그 토큰은 로그인할 때마다 바뀌므로 "
                          "login에 extract로 뽑아 entries.headers에 ${토큰이름}으로 넣으세요.")

    return mask_secrets(recipe, secrets)


def save(recipe, out, password=None):
    text = json.dumps(recipe, ensure_ascii=False, indent=2)
    if password and password in text:
        print("실패: 비밀번호가 결과에 남아 저장하지 않습니다.", file=sys.stderr)
        return 1
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\n%s 를 만들었어요." % out)
    print("다음: python parking_watch.py --config %s   (미리보기)" % out)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="브라우저 기록으로 주차 레시피 만들기")
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--plate", help="내 차량번호")
    p.add_argument("--user", default=os.environ.get("PARKING_USER"))
    p.add_argument("--password", default=os.environ.get("PARKING_PASS"),
                   help="넘기면 로그인 요청을 더 정확히 찾는다. 안 넘기고 브라우저에 직접 입력해도 된다.")
    p.add_argument("--headless", action="store_true", help="화면 없이 (자동화 테스트용)")
    p.add_argument("--dump-dir", help="기록한 요청을 원본 그대로 저장할 폴더")
    p.add_argument("-o", "--out", default="parking_site.json")
    args = p.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright가 없어요:  pip install playwright && playwright install chromium", file=sys.stderr)
        return 2

    records = []
    with sync_playwright() as pw:
        browser = launch_browser(pw, args.headless)
        page = browser.new_page()
        attach(page, records)
        page.goto(args.url)

        print("\n브라우저에서 이렇게 해주세요:")
        print("  1) 로그인")
        print("  2) 입차 차량 목록 화면을 열고 한 번 새로고침")
        print("  3) 아무 차량이나 무료등록을 한 번 실제로 누르기")
        print("\n다 했으면 이 창에서 Enter를 누르세요. (요청 %s개 기록 중)" % "…")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        browser.close()

    print("요청 %d개를 기록했어요." % len(records))
    if args.dump_dir:
        os.makedirs(args.dump_dir, exist_ok=True)
        for record in records:
            with open(os.path.join(args.dump_dir, "%03d.json" % record.order), "w", encoding="utf-8") as f:
                json.dump({"url": record.url, "method": record.method, "headers": record.headers,
                           "body": record.post_data, "response": (record.response_text or "")[:20000]},
                          f, ensure_ascii=False, indent=2)

    recipe = build_recipe(records, args.plate, args.user, args.password)
    return save(recipe, args.out, args.password)


if __name__ == "__main__":
    sys.exit(main())
