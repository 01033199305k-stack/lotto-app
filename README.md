# 로또 번호 추첨기 웹앱

**🔗 바로 써보기: https://lotto-app-m0fe.onrender.com**

로또 6/45와 연금복권720+ 과거 당첨 데이터를 분석해 번호를 추천해주는 무료 웹앱입니다. 신뢰도·빈도·혼합·무작위 전략으로 번호를 뽑고, 최신 당첨결과와 자동으로 대조해볼 수 있습니다.

기존 `동반출현_전체데이터.csv` 분석 로직(drawer.py, analyze_advanced_simple.py)을 Flask API로 옮기고 웹 UI를 붙인 버전입니다.

## 실행

```
cd webapp
pip install -r requirements.txt
python app.py
```

브라우저에서 http://127.0.0.1:5050 접속.

## 구성

- `app.py` — Flask 서버. CSV를 한 번 로드해 번호별 신뢰도 점수(2/3/4개 동반출현 가중 합산)와 빈도를 계산.
  - `/api/draw/<strategy>` — strategy: `reliability`(신뢰도) / `frequency`(빈도) / `mixed`(혼합) / `random`(무작위)
  - `/api/stats` — 신뢰도 상위 15개 번호 점수
- `templates/index.html`, `static/style.css`, `static/app.js` — 로또공 UI, 다크모드 지원

## 배포 (외부 공개 + 광고 수익화하려면)

Render, Railway, PythonAnywhere 등에 그대로 올리면 무료로 공개 가능합니다. 이후 페이지에 Google AdSense 스니펫만 추가하면 됩니다.

## 곁다리: 자동 무료주차 등록

로또와는 무관하지만 같은 저장소에서 돌리는 개인용 자동화. 주차등록 사이트에 주기적으로
들어가 내 차가 입차해 있으면 무료주차를 대신 눌러준다. 사이트별 설정은 레시피(JSON) 한 장.

- `parking_watch.py` — 로그인 → 입차 목록 → 내 차 무료등록
- `capture_requests.py` — 브라우저를 띄워 요청을 받아적고 레시피 자동 생성
- `curl_to_recipe.py` — 개발자도구 cURL을 레시피로 변환 (비밀번호는 자리표시자로)
- `parking_site.example.json` — 레시피 예시
- `.github/workflows/parking-watch.yml` — 5분마다 자동 실행
- 설정 방법은 [PARKING.md](PARKING.md)
