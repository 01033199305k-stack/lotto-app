# -*- coding: utf-8 -*-
"""로또 용지 QR코드에 박힌 URL에서 회차와 게임 번호를 뽑아낸다.

용지 QR은 동행복권 조회 페이지로 연결되고, 번호는 쿼리스트링의 v 값에 들어있다:

    http://m.dhlottery.co.kr/qr.do?method=winQr&v=1141q081018252745q071119232729...

v = 회차(4자리) + [게임구분자 1글자 + 번호 12자리] * 게임수 (+ 뒤에 일련번호가 붙기도 함)
구분자 글자는 자동/수동/반자동을 뜻하지만 당첨 판정과는 무관하므로 무시한다.

구분자 종류가 바뀌거나 뒤에 뭐가 더 붙어도 깨지지 않도록, 글자를 기준으로 자르는 대신
'12자리 연속 숫자'를 전부 찾아서 1~45 범위의 서로 다른 6개인 것만 게임으로 인정한다.
"""
import re

QR_HOST_HINT = "dhlottery"
GAME_RE = re.compile(r"\d{12}")
V_RE = re.compile(r"[?&]v=([0-9A-Za-z]+)")


class TicketParseError(ValueError):
    pass


def _games_from_body(body):
    games = []
    for chunk in GAME_RE.findall(body):
        nums = [int(chunk[i:i + 2]) for i in range(0, 12, 2)]
        if len(set(nums)) == 6 and all(1 <= n <= 45 for n in nums):
            games.append(sorted(nums))
    return games


def parse_qr(text):
    """QR 문자열 -> {"round": int, "games": [[6개], ...]}"""
    if not text or not isinstance(text, str):
        raise TicketParseError("QR 내용이 비어 있어요.")

    text = text.strip()
    m = V_RE.search(text)
    if not m:
        # QR 리더가 URL 없이 v 값만 넘겨주는 경우도 받아준다.
        raw = text if re.fullmatch(r"[0-9A-Za-z]+", text) else None
        if raw is None:
            raise TicketParseError("로또 용지 QR이 아닌 것 같아요.")
    else:
        raw = m.group(1)

    if len(raw) < 16:  # 회차 4자리 + 최소 한 게임 12자리
        raise TicketParseError("QR에서 번호를 찾지 못했어요.")

    if not raw[:4].isdigit():
        raise TicketParseError("회차를 읽지 못했어요.")

    round_no = int(raw[:4])
    games = _games_from_body(raw[4:])

    if not games:
        raise TicketParseError("QR에서 유효한 번호 조합을 찾지 못했어요.")
    if not 1 <= round_no <= 9999:
        raise TicketParseError(f"회차({round_no})가 이상해요.")

    # 같은 용지에 동일 조합이 두 번 찍히는 일은 없으니 중복은 제거한다.
    seen, unique = set(), []
    for g in games:
        key = tuple(g)
        if key not in seen:
            seen.add(key)
            unique.append(g)

    return {"round": round_no, "games": unique}
