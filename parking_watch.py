# -*- coding: utf-8 -*-
"""주차등록 사이트를 주기적으로 훑어서, 내 차가 입차해 있으면 무료주차를 눌러준다.

주차등록 사이트는 업체마다 주소도 화면도 달라서 사이트별 코드를 새로 짜는 대신
'레시피'(JSON) 한 장으로 동작을 기술한다.  레시피에는 아래 세 요청이 들어간다.

    login    (선택) 로그인.  CSRF 토큰이 필요하면 prepare 단계에서 먼저 뽑는다.
    entries  입차 목록 조회.  응답이 JSON이면 list_path/fields로, HTML이면 row_regex로 읽는다.
    register 무료등록.  ${entry.id} 처럼 목록에서 뽑은 값을 그대로 끼워 넣는다.

    python parking_watch.py --config parking_site.json            # 미리보기(등록 안 함)
    python parking_watch.py --config parking_site.json --commit   # 실제 등록
    python parking_watch.py --config parking_site.json --commit --watch 300  # 5분마다

아이디·비밀번호는 레시피에 직접 쓰지 말고 ${PARKING_USER} 처럼 두고 환경변수로 넣는다.
레시피 작성법과 예시는 parking_site.example.json, 사이트 조사 방법은 README를 본다.
"""
import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
VAR_RE = re.compile(r"\$\{([A-Za-z0-9_.]+)\}")
TAIL4_RE = re.compile(r"(\d{4})$")


class ConfigError(ValueError):
    """레시피가 잘못됐을 때. 고치기 전엔 몇 번을 돌려도 같은 결과다."""


class StepError(RuntimeError):
    """요청 한 단계가 실패했을 때. 일시적일 수도 있어서 다음 회차에 다시 시도한다."""


def log(msg):
    print("[%s] %s" % (datetime.now(KST).strftime("%m-%d %H:%M:%S"), msg), flush=True)


# ---------------------------------------------------------------- 값 채우기

def render(value, ctx):
    """${NAME}을 ctx 값이나 환경변수로 바꾼다. dict/list면 안쪽까지 훑는다."""
    if isinstance(value, dict):
        return {k: render(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, ctx) for v in value]
    if not isinstance(value, str):
        return value

    def sub(m):
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        env = os.environ.get(key)
        if env is None:
            raise ConfigError("${%s} 값이 없어요. 환경변수(또는 Actions secret)를 설정했는지 보세요." % key)
        return env

    return VAR_RE.sub(sub, value)


# ---------------------------------------------------------------- HTTP

class Client:
    """쿠키를 물고 다니는 최소한의 HTTP 클라이언트. 로그인 세션이 유지돼야 해서 필요하다."""

    def __init__(self, timeout=20, retries=2, headers=None):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.timeout = timeout
        self.retries = retries
        self.headers = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}
        if headers:
            self.headers.update(headers)

    def request(self, url, method="GET", body=None, content_type="form", headers=None):
        method = method.upper()
        head = dict(self.headers)
        if headers:
            head.update(headers)

        data = None
        if body:
            if method == "GET":
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(body, encoding="utf-8")
            elif content_type == "json":
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                head.setdefault("Content-Type", "application/json; charset=utf-8")
            else:
                data = urllib.parse.urlencode(body, encoding="utf-8").encode("utf-8")
                head.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")

        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=head, method=method)
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return resp.status, resp.read().decode(charset, "replace")
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                if e.code < 500:
                    # 4xx는 다시 보내도 같은 답이 온다. 판정은 호출한 쪽에 맡긴다.
                    return e.code, text
                last = "HTTP %s" % e.code
            except Exception as e:  # 네트워크 끊김, 타임아웃 등
                last = "%s: %s" % (type(e).__name__, e)
            if attempt < self.retries:
                time.sleep(2 ** attempt)
        raise StepError("요청 실패 (%s) %s" % (last, url))


def run_step(client, spec, ctx, label):
    """레시피의 한 단계를 실행하고 응답 본문을 돌려준다. extract가 있으면 ctx에 담는다."""
    text = _fire(client, spec, ctx)

    for key, pattern in (spec.get("extract") or {}).items():
        m = re.search(pattern, text, re.S)
        if not m:
            raise StepError("%s 응답에서 '%s' 값을 못 찾았어요. 정규식을 확인하세요." % (label, key))
        ctx[key] = m.group(1) if m.groups() else m.group(0)
    return text


def _fire(client, spec, ctx):
    if "url" not in spec:
        raise ConfigError("단계에 url이 없어요.")
    status, text = client.request(
        render(spec["url"], ctx),
        spec.get("method", "GET"),
        render(spec.get("body"), ctx),
        spec.get("content_type", "form"),
        render(spec.get("headers"), ctx),
    )

    ok = 200 <= status < 400
    if "expect_status" in spec:
        ok = status == spec["expect_status"]
    need = spec.get("success_contains")
    if ok and need and need not in text:
        ok = False
    bad = spec.get("failure_contains")
    if ok and bad and bad in text:
        ok = False
    if not ok:
        raise StepError("HTTP %s / 응답 앞부분: %s" % (status, _snippet(text)))
    return text


def _snippet(text, n=200):
    return re.sub(r"\s+", " ", text)[:n]


# ---------------------------------------------------------------- 입차 목록 읽기

def dig(obj, path):
    """'data.list' 또는 'car.0.no' 처럼 점으로 이어진 경로를 따라간다."""
    cur = obj
    for part in path.split("."):
        if not part:
            continue
        if isinstance(cur, list):
            if not part.isdigit() or int(part) >= len(cur):
                return None
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def parse_entries(text, spec):
    fmt = spec.get("format", "json")

    if fmt == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            raise StepError("입차 목록이 JSON이 아니에요. format을 \"html\"로 두고 row_regex를 쓰세요.")
        rows = dig(payload, spec["list_path"]) if spec.get("list_path") else payload
        if rows is None:
            raise StepError("입차 목록에서 list_path(%s)를 못 찾았어요." % spec.get("list_path"))
        if not isinstance(rows, list):
            raise StepError("list_path(%s)가 배열이 아니에요." % spec.get("list_path"))
        fields = spec.get("fields") or {}
        if "plate" not in fields:
            raise ConfigError("fields에 차량번호를 가리키는 'plate'가 있어야 해요.")
        out = []
        for row in rows:
            item = {"raw": json.dumps(row, ensure_ascii=False)}
            for name, key in fields.items():
                item[name] = dig(row, key)
            out.append(item)
        return out

    if fmt == "html":
        pattern = spec.get("row_regex")
        if not pattern:
            raise ConfigError("format이 \"html\"이면 row_regex가 필요해요.")
        if "(?P<plate>" not in pattern:
            raise ConfigError("row_regex에 차량번호를 잡는 (?P<plate>...) 그룹이 있어야 해요.")
        out = []
        for m in re.finditer(pattern, text, re.S):
            item = dict(m.groupdict())
            item["raw"] = m.group(0)
            out.append(item)
        return out

    raise ConfigError("알 수 없는 format: %s (json 또는 html)" % fmt)


# ---------------------------------------------------------------- 차량번호 대조

def normalize_plate(value):
    """'서울 12가 3456' -> '서울12가3456'. 공백·하이픈만 털고 마스킹(*)은 남긴다."""
    if value is None:
        return ""
    return re.sub(r"[^0-9A-Za-z가-힣*]", "", str(value)).upper()


def _masked_equal(a, b):
    return len(a) == len(b) and all(x == "*" or y == "*" or x == y for x, y in zip(a, b))


def plate_matches(entry_plate, my_plates, mode="masked"):
    """mode: exact(그대로) / masked(사이트가 12가34** 처럼 가린 경우까지) / tail4(뒤 4자리만)."""
    got = normalize_plate(entry_plate)
    if not got:
        return False
    for mine in my_plates:
        want = normalize_plate(mine)
        if not want:
            continue
        if got == want:
            return True
        if mode == "masked" and _masked_equal(got, want):
            return True
        if mode == "tail4":
            g, w = TAIL4_RE.search(got), TAIL4_RE.search(want)
            if g and w and g.group(1) == w.group(1):
                return True
    return False


def already_registered(entry, spec):
    """사이트가 '할인 적용됨'을 알려주면 그 표시를 믿는다. 기록 파일보다 이쪽이 정확하다."""
    rule = spec.get("already_when")
    if not rule:
        return False
    value = entry.get(rule.get("field", "raw"))
    if value is None:
        return False
    value = str(value)
    if "equals" in rule:
        return value in [str(v) for v in rule["equals"]]
    if "contains" in rule:
        return rule["contains"] in value
    raise ConfigError("already_when에는 equals 또는 contains가 필요해요.")


# ---------------------------------------------------------------- 중복 방지 기록

class State:
    """이미 등록한 입차 건을 기억해 같은 차를 두 번 등록하지 않는다.

    GitHub Actions처럼 매번 새 머신에서 도는 곳에서는 이 파일이 날아가므로,
    가능하면 레시피의 already_when으로 사이트 표시를 보는 쪽이 확실하다.
    """

    def __init__(self, path, keep_hours=24):
        self.path = path
        self.keep = timedelta(hours=keep_hours)
        self.done = {}
        if path and os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.done = json.load(f).get("done", {})
            except (OSError, ValueError):
                log("기록 파일을 읽지 못해 빈 상태로 시작해요: %s" % path)

    def seen(self, key):
        return key in self.done

    def mark(self, key):
        self.done[key] = datetime.now(timezone.utc).isoformat()

    def save(self):
        if not self.path:
            return
        cutoff = datetime.now(timezone.utc) - self.keep
        kept = {}
        for key, stamp in self.done.items():
            try:
                if datetime.fromisoformat(stamp) >= cutoff:
                    kept[key] = stamp
            except ValueError:
                continue
        self.done = kept
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"done": kept}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- 실행

def notify(cfg, message):
    """등록됐을 때 알림 한 줄. 주차 사이트 쿠키가 같이 나가지 않게 새 클라이언트를 쓴다."""
    spec = cfg.get("notify")
    if not spec:
        return
    try:
        _fire(Client(timeout=10, retries=0), spec, {"message": message})
    except Exception as e:
        log("알림 실패(무시하고 계속): %s" % e)


def entry_key(entry):
    """같은 입차 건을 가리키는 열쇠. 사이트가 주는 id가 제일 믿을 만하다."""
    ident = entry.get("id")
    if ident not in (None, ""):
        return str(ident)
    return "%s|%s" % (normalize_plate(entry.get("plate")), entry.get("entered_at") or "")


def load_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise ConfigError("레시피 파일이 없어요: %s (parking_site.example.json을 복사해 쓰세요)" % path)
    except ValueError as e:
        raise ConfigError("레시피 JSON이 깨졌어요: %s" % e)

    for key in ("plates", "entries", "register"):
        if key not in cfg:
            raise ConfigError("레시피에 '%s' 항목이 없어요." % key)
    if not isinstance(cfg["plates"], list) or not any(str(p).strip() for p in cfg["plates"]):
        raise ConfigError("등록할 차량번호(plates)가 비어 있어요.")
    return cfg


def run_once(cfg, commit=False, state_path=None):
    """한 바퀴: 로그인 -> 입차 목록 -> 내 차 골라 무료등록. 등록한 건수를 돌려준다."""
    ctx = {}
    client = Client(cfg.get("timeout", 20), cfg.get("retries", 2), cfg.get("headers"))
    state = State(state_path or cfg.get("state_file"), cfg.get("state_keep_hours", 24))

    login = cfg.get("login")
    if login:
        if login.get("prepare"):
            run_step(client, login["prepare"], ctx, "로그인 준비")
        run_step(client, login, ctx, "로그인")
        log("로그인 완료")

    entries = parse_entries(run_step(client, cfg["entries"], ctx, "입차 목록 조회"), cfg["entries"])
    log("입차 목록 %d건" % len(entries))

    mode = cfg.get("plate_match", "masked")
    mine = [e for e in entries if plate_matches(e.get("plate"), cfg["plates"], mode)]
    if not mine:
        log("내 차는 아직 목록에 없어요.")
        state.save()
        return 0

    registered = 0
    for entry in mine:
        key = entry_key(entry)
        label = "%s (%s)" % (entry.get("plate"), key)

        if already_registered(entry, cfg["entries"]):
            log("이미 등록돼 있어요(사이트 표시): %s" % label)
            state.mark(key)
            continue
        if state.seen(key):
            log("이미 등록했어요(기록): %s" % label)
            continue
        if not commit:
            log("[미리보기] 여기서 무료등록을 호출해요: %s" % label)
            continue

        step_ctx = dict(ctx)
        for name, value in entry.items():
            step_ctx["entry." + name] = "" if value is None else value
        run_step(client, cfg["register"], step_ctx, "무료등록")
        state.mark(key)
        registered += 1
        log("무료주차 등록 완료: %s" % label)
        notify(cfg, "무료주차 등록 완료: %s" % entry.get("plate"))

    state.save()
    return registered


def main(argv=None):
    p = argparse.ArgumentParser(description="입차한 내 차를 자동으로 무료주차 등록한다.")
    p.add_argument("--config", default=os.environ.get("PARKING_CONFIG", "parking_site.json"),
                   help="사이트 레시피 JSON 경로")
    p.add_argument("--commit", action="store_true",
                   help="실제로 등록한다. 없으면 무엇을 등록할지 보여주기만 한다.")
    p.add_argument("--state", default=os.environ.get("PARKING_STATE"),
                   help="중복 등록 방지 기록 파일 경로")
    p.add_argument("--watch", type=int, metavar="초",
                   help="이 간격으로 계속 돈다. 없으면 한 번만 돌고 끝난다.")
    args = p.parse_args(argv)

    commit = args.commit or os.environ.get("PARKING_COMMIT") == "1"
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        log("설정 오류: %s" % e)
        return 2

    if not commit:
        log("미리보기 모드예요. 실제로 등록하려면 --commit 을 붙이세요.")

    interval = args.watch
    while True:
        try:
            run_once(cfg, commit, args.state)
        except ConfigError as e:
            log("설정 오류: %s" % e)
            return 2  # 레시피가 틀린 거라 계속 돌아봐야 소용없다.
        except StepError as e:
            log("이번 회차 실패: %s" % e)
            if not interval:
                return 1
        if not interval:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
