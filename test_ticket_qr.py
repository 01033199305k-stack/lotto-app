# -*- coding: utf-8 -*-
"""용지 QR 파서 테스트.  실행: python test_ticket_qr.py

실물 용지가 있어야 확인 가능한 부분(카메라, 실제 QR 이미지)은 여기서 못 잡는다.
대신 v 값의 형식 해석과 잘못된 입력 거부는 전부 여기서 막는다.
"""
import sys

from ticket_qr import TicketParseError, parse_qr

G1 = [8, 10, 18, 25, 27, 45]
G2 = [7, 11, 19, 23, 27, 29]
G3 = [2, 13, 18, 32, 38, 42]


def enc(nums):
    return "".join("%02d" % n for n in nums)


def url(v):
    return "http://m.dhlottery.co.kr/qr.do?method=winQr&v=" + v


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn

    return deco


@case("표준 URL에서 회차와 게임을 읽는다")
def _():
    r = parse_qr(url("1141q%s q%s q%s".replace(" ", "") % (enc(G1), enc(G2), enc(G3))))
    assert r["round"] == 1141, r
    assert r["games"] == [sorted(G1), sorted(G2), sorted(G3)], r


@case("구분자가 m/s여도 동작한다")
def _():
    r = parse_qr(url("1238m%ss%s" % (enc(G1), enc(G2))))
    assert len(r["games"]) == 2, r


@case("뒤에 붙은 일련번호는 무시한다")
def _():
    r = parse_qr(url("1238q%sz999" % enc(G1)))
    assert r["games"] == [sorted(G1)], r


@case("URL 없이 v 값만 줘도 동작한다")
def _():
    r = parse_qr("1238q%s" % enc(G1))
    assert r["round"] == 1238, r


@case("한 게임짜리 용지도 동작한다")
def _():
    r = parse_qr(url("1238q%s" % enc(G1)))
    assert r["games"] == [sorted(G1)], r


@case("같은 조합이 두 번 나오면 하나로 합친다")
def _():
    r = parse_qr("1238q%sq%s" % (enc(G1), enc(G1)))
    assert len(r["games"]) == 1, r


def rejects(text):
    try:
        parse_qr(text)
    except TicketParseError:
        return
    raise AssertionError("거부돼야 하는데 통과됨: %r" % (text,))


@case("빈 문자열을 거부한다")
def _():
    rejects("")


@case("로또와 무관한 URL을 거부한다")
def _():
    rejects("https://naver.com")


@case("46 이상 번호를 거부한다")
def _():
    rejects("1238q" + enc([46, 1, 2, 3, 4, 5]))


@case("0번을 거부한다")
def _():
    rejects("1238q" + enc([0, 1, 2, 3, 4, 5]))


@case("번호가 중복된 조합을 거부한다")
def _():
    rejects("1238q080808101010")


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
