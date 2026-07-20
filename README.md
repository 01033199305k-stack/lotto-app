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
