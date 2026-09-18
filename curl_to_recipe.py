# -*- coding: utf-8 -*-
"""브라우저에서 복사한 cURL 명령을 parking_watch.py 레시피로 바꿔준다.

크롬 개발자도구 Network 탭에서 요청을 우클릭 -> Copy -> Copy as cURL 한 걸
파일로 저장해 넘기면, 레시피 JSON을 만들어 준다.  아이디·비밀번호는 자동으로
${PARKING_USER}/${PARKING_PASS} 자리표시자로 바꿔서 파일에 평문이 남지 않게 한다.

    python curl_to_recipe.py \
        --login login.txt --entries list.txt --register register.txt \
        --entries-response list.json \
        --plate 12가3456 --user store01 \
        -o parking_site.json

입차 목록 응답(JSON)을 --entries-response로 같이 주면 배열 위치와 차량번호 키를
알아서 찾아 list_path/fields까지 채운다.  응답은 Network 탭 Response에서 복사한다.
"""
import argparse
import json
import os
import re
import shlex
import sys
import urllib.parse

# 12가3456 / 123가4567 / 서울12가3456, 가린 자리(*)까지 차량번호로 본다.
PLATE_RE = re.compile(r"(?:[가-힣]{2})?\d{2,3}[가-힣][\d*]{4}")

# 브라우저가 붙이는 잡다한 헤더는 레시피에 넣어봐야 방해만 된다.
DROP_HEADERS = {
    "cookie", "content-length", "host", "connection", "accept-encoding",
    "user-agent", "pragma", "cache-control", "te", "upgrade-insecure-requests",
    "priority", "dnt",
}
ID_HINTS = ("seq", "id", "no", "idx", "key", "uid", "num")


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------- cURL 해석

def parse_curl(text):
    """cURL 명령 한 줄(또는 여러 줄) -> {url, method, headers, body, content_type}"""
    text = text.strip()
    if not text:
        raise ParseError("내용이 비어 있어요.")
    # 줄 끝의 역슬래시와 윈도우식 캐럿을 정리해 한 줄로 만든다.
    text = re.sub(r"\\\s*\n", " ", text)
    text = re.sub(r"\^\s*\n", " ", text)
    text = text.replace("\n", " ")

    try:
        tokens = shlex.split(text)
    except ValueError as e:
        raise ParseError("따옴표가 안 맞아요: %s" % e)
    if not tokens or tokens[0] != "curl":
        raise ParseError("curl로 시작하는 명령이 아니에요. 'Copy as cURL (bash)'로 복사했는지 보세요.")

    url = None
    method = None
    headers = {}
    body = None

    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("-H", "--header") and i + 1 < len(tokens):
            i += 1
            if ":" in tokens[i]:
                name, _, value = tokens[i].partition(":")
                headers[name.strip()] = value.strip()
        elif tok in ("-X", "--request") and i + 1 < len(tokens):
            i += 1
            method = tokens[i].upper()
        elif tok in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii") and i + 1 < len(tokens):
            i += 1
            body = tokens[i]
        elif tok in ("-b", "--cookie") and i + 1 < len(tokens):
            i += 1  # 쿠키는 로그인해서 새로 받는다. 남의 세션을 박제하면 금방 만료된다.
        elif tok.startswith("-"):
            # 값이 따로 붙는 옵션들은 값까지 같이 건너뛴다.
            if tok in ("-A", "--user-agent", "-e", "--referer", "--compressed-flag") and i + 1 < len(tokens):
                i += 1
        elif url is None:
            url = tok
        i += 1

    if not url:
        raise ParseError("URL을 못 찾았어요.")
    if method is None:
        method = "POST" if body else "GET"

    content_type = "form"
    for name, value in headers.items():
        if name.lower() == "content-type" and "json" in value.lower():
            content_type = "json"
    if body and body.lstrip().startswith(("{", "[")):
        content_type = "json"

    return {"url": url, "method": method, "headers": headers, "body": body,
            "content_type": content_type}


def body_to_dict(body, content_type):
    """요청 본문을 레시피에 넣을 dict로. 해석 못 하면 문자열 그대로 둔다."""
    if body is None:
        return None
    if content_type == "json":
        try:
            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else {"_raw": body}
        except ValueError:
            pass
    if "=" in body:
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        if parsed:
            return {k: v[0] for k, v in parsed.items()}
    return {"_raw": body}


def clean_headers(headers):
    out = {}
    for name, value in headers.items():
        low = name.lower()
        if low in DROP_HEADERS or low.startswith("sec-") or low == "content-type":
            continue
        out[name] = value
    return out


def to_step(curl, secrets):
    """cURL 결과 -> 레시피 단계. secrets에 든 값은 ${이름}으로 바꾼다."""
    step = {"url": curl["url"], "method": curl["method"]}
    body = body_to_dict(curl["body"], curl["content_type"])

    if curl["method"] == "GET" and body is None:
        # 쿼리스트링은 url에 그대로 둔다. 분리하면 오히려 읽기 나빠진다.
        pass
    if body is not None:
        step["content_type"] = curl["content_type"]
        step["body"] = body

    headers = clean_headers(curl["headers"])
    if headers:
        step["headers"] = headers

    return mask_secrets(step, secrets)


def mask_secrets(value, secrets):
    """아이디/비밀번호 같은 값을 ${환경변수}로 바꿔 파일에 평문이 안 남게 한다."""
    if isinstance(value, dict):
        return {k: mask_secrets(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_secrets(v, secrets) for v in value]
    if isinstance(value, str):
        for literal, name in secrets:
            if literal and literal in value:
                value = value.replace(literal, "${%s}" % name)
    return value


# ---------------------------------------------------------------- 응답 구조 추측

def looks_like_plate(value):
    return isinstance(value, str) and bool(PLATE_RE.fullmatch(value.replace(" ", "")))


def guess_entries_spec(payload):
    """입차 목록 응답에서 배열 위치와 차량번호/식별자/할인표시 키를 찾아본다."""
    best = None

    def walk(node, path):
        nonlocal best
        if isinstance(node, list):
            dicts = [x for x in node if isinstance(x, dict)]
            if dicts:
                for key in dicts[0]:
                    if any(looks_like_plate(d.get(key)) for d in dicts):
                        score = len(dicts)
                        if best is None or score > best[0]:
                            best = (score, path, key, dicts)
                        break
            for idx, item in enumerate(node[:3]):
                walk(item, "%s.%s" % (path, idx) if path else str(idx))
        elif isinstance(node, dict):
            for key, item in node.items():
                walk(item, "%s.%s" % (path, key) if path else key)

    walk(payload, "")
    if best is None:
        return None

    _, path, plate_key, rows = best
    fields = {"plate": plate_key}

    # 입차 건 식별자: 이름에 seq/id/no 가 들어가고 행마다 값이 다른 키.
    for key in rows[0]:
        if key == plate_key:
            continue
        if any(h in key.lower() for h in ID_HINTS):
            values = [r.get(key) for r in rows]
            if len(set(map(str, values))) == len(values) and all(v not in (None, "") for v in values):
                fields["id"] = key
                break

    # 입차 시각: 날짜처럼 생긴 값.
    for key, value in rows[0].items():
        if key in fields.values():
            continue
        if isinstance(value, str) and re.search(r"\d{2}:\d{2}", value):
            fields["entered_at"] = key
            break

    spec = {"format": "json", "fields": fields}
    if path:
        spec["list_path"] = path

    # 할인 적용 여부로 쓸 만한 Y/N 플래그가 있으면 already_when 후보로 적어둔다.
    for key, value in rows[0].items():
        if key in fields.values():
            continue
        if str(value).upper() in ("Y", "N") or "dc" in key.lower() or "discount" in key.lower():
            spec["_already_when_후보"] = {"field": key, "equals": ["Y"]}
            break

    return spec


# ---------------------------------------------------------------- 조립

def sample_ids(payload, spec):
    """샘플 응답에서 입차 건 식별자 값들을 모은다. 등록 요청의 어느 값이 그건지 찾는 데 쓴다."""
    key = (spec.get("fields") or {}).get("id")
    if not key or payload is None:
        return set()
    from parking_watch import dig
    rows = dig(payload, spec["list_path"]) if spec.get("list_path") else payload
    if not isinstance(rows, list):
        return set()
    return {str(r.get(key)) for r in rows if isinstance(r, dict) and r.get(key) not in (None, "")}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def build(args):
    secrets = []
    if args.password:
        secrets.append((args.password, "PARKING_PASS"))
    if args.user:
        secrets.append((args.user, "PARKING_USER"))

    recipe = {
        "_설명": "curl_to_recipe.py가 만든 초안. 자동 추측이 섞여 있으니 --commit 전에 미리보기로 꼭 확인하세요.",
        "plates": [args.plate] if args.plate else ["여기에 내 차량번호"],
        "plate_match": "masked",
        "state_file": ".parking_state.json",
    }

    if args.login:
        login = to_step(parse_curl(read(args.login)), secrets)
        if args.user and "${PARKING_USER}" not in json.dumps(login, ensure_ascii=False):
            print("  주의: 로그인 요청 본문에서 아이디를 못 찾았어요. body를 직접 확인하세요.", file=sys.stderr)
        recipe["login"] = login

    entries = to_step(parse_curl(read(args.entries)), secrets)
    known_ids = set()
    if args.entries_response:
        raw = read(args.entries_response)
        try:
            payload = json.loads(raw)
            guessed = guess_entries_spec(payload)
        except ValueError:
            print("  주의: 응답이 JSON이 아니에요. format을 html로 두고 row_regex를 직접 쓰세요.", file=sys.stderr)
            payload, guessed = None, None
        if guessed:
            known_ids = sample_ids(payload, guessed)
            entries.update(guessed)
            print("  입차 목록 구조 추측: list_path=%s fields=%s"
                  % (guessed.get("list_path", "(최상위 배열)"), guessed["fields"]), file=sys.stderr)
        else:
            print("  주의: 응답에서 차량번호처럼 생긴 값을 못 찾았어요. fields를 직접 채우세요.", file=sys.stderr)
    if "fields" not in entries:
        entries.setdefault("format", "json")
        entries["fields"] = {"plate": "차량번호가_들어있는_키", "id": "입차건_식별자_키"}
    recipe["entries"] = entries

    register = to_step(parse_curl(read(args.register)), secrets)
    body = register.get("body")
    if isinstance(body, dict):
        # 등록 요청에 박혀 있는 값 중 목록에서 뽑을 수 있는 건 ${entry.*}로 바꿔준다.
        # 어느 입차 건을 가리키는 값인지는 샘플 응답의 id 목록과 대조해 찾는다.
        if args.sample_id:
            known_ids.add(str(args.sample_id))
        for key, value in list(body.items()):
            if looks_like_plate(str(value)):
                body[key] = "${entry.plate}"
            elif str(value) in known_ids:
                body[key] = "${entry.id}"
    if "success_contains" not in register:
        register["_할일"] = "성공 응답에만 들어있는 문자열을 success_contains에 넣으세요 (실패도 200을 주는 사이트가 많음)."
    recipe["register"] = register

    return recipe


def main(argv=None):
    p = argparse.ArgumentParser(description="Copy as cURL -> parking_watch 레시피")
    p.add_argument("--login", help="로그인 요청 cURL 파일 (없으면 생략)")
    p.add_argument("--entries", required=True, help="입차 목록 요청 cURL 파일")
    p.add_argument("--register", required=True, help="무료등록 요청 cURL 파일")
    p.add_argument("--entries-response", help="입차 목록 응답 JSON 파일 (구조 자동 추측용)")
    p.add_argument("--plate", help="내 차량번호")
    p.add_argument("--user", default=os.environ.get("PARKING_USER"), help="사이트 아이디 (자리표시자로 치환)")
    p.add_argument("--password", default=os.environ.get("PARKING_PASS"), help="사이트 비밀번호 (자리표시자로 치환)")
    p.add_argument("--sample-id", help="등록 요청에 박힌 입차 건 식별자 (샘플 응답을 안 줄 때만 필요)")
    p.add_argument("-o", "--out", default="parking_site.json")
    args = p.parse_args(argv)

    try:
        recipe = build(args)
    except (ParseError, OSError) as e:
        print("실패: %s" % e, file=sys.stderr)
        return 1

    text = json.dumps(recipe, ensure_ascii=False, indent=2)
    if args.password and args.password in text:
        print("실패: 비밀번호가 결과에 그대로 남았어요. 저장하지 않습니다.", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("%s 를 만들었어요. 다음: python parking_watch.py --config %s" % (args.out, args.out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
