# 입차하면 자동으로 무료주차 등록하기

주차등록 사이트에 5분마다 로그인해서 입차 목록을 보고, 내 차가 있으면 무료등록 버튼에
해당하는 요청을 대신 보낸다. 사이트마다 주소·화면이 달라서, 코드를 고치는 대신
**레시피 파일(JSON) 한 장**만 채우면 되게 만들었다.

> 내 계정으로 로그인해서, 내가 원래 누를 수 있는 버튼을 대신 누르는 용도다.
> 남의 계정이나 권한 없는 할인에는 쓰지 말 것. 사이트 약관도 한 번 확인하는 게 좋다.

## 3분 요약

| 단계 | 할 일 |
| --- | --- |
| 1 | 브라우저 개발자도구로 사이트의 요청 3개(로그인·입차목록·무료등록)를 확인 |
| 2 | `parking_site.example.json`을 `parking_site.json`으로 복사해 그 3개를 적는다 |
| 3 | `python parking_watch.py --config parking_site.json` 으로 **미리보기** 확인 |
| 4 | 맞으면 `--commit` 붙여 실제 등록, 그 다음 GitHub Actions에 올려 자동화 |

## 1. 사이트 요청 알아내기

크롬에서 주차등록 사이트를 열고 `F12` → **Network** 탭 → `Fetch/XHR` 필터를 켠 뒤:

- **로그인** — 아이디/비번 넣고 로그인. 목록에 뜬 요청의 `Request URL`, `Form Data`를 적는다.
  - 로그인 폼에 `_csrf`, `authenticity_token` 같은 숨은 값이 있으면 레시피의 `login.prepare.extract`로 먼저 뽑아 쓴다.
  - 로그인이 **문자 인증·카카오 로그인·캡차**를 요구하면 이 방식으로는 안 된다. 아래 "안 되는 경우"를 본다.
- **입차 목록** — 입차 차량 화면을 새로고침. 응답이 JSON이면 `Preview` 탭에서 배열 위치(`data.list` 등)와
  차량번호 키 이름(`carNo` 등)을 적는다. HTML이 통째로 오면 `format: "html"` + 정규식을 쓴다.
- **무료등록** — 아무 차나 하나 등록해 보고, 그때 나간 요청의 URL·본문을 적는다.
  본문에서 입차 건을 가리키는 값(`inSeq` 등)은 목록에서 뽑아 `${entry.id}`로 끼워 넣는다.

요청 위에서 우클릭 → **Copy as cURL** 해두면 헤더까지 그대로 볼 수 있어 편하다.

## 2. 레시피 채우기

```bash
cp parking_site.example.json parking_site.json
```

| 항목 | 뜻 |
| --- | --- |
| `plates` | 내 차량번호. 여러 대면 다 적는다. |
| `plate_match` | `masked`(기본, `12가34**`처럼 가린 표시도 맞춤) / `exact` / `tail4`(뒤 4자리만 — 남의 차와 겹칠 수 있으니 주의) |
| `login` | 로그인 요청. 필요 없으면 통째로 빼도 된다. `prepare`는 CSRF 토큰 같은 선행 조회. |
| `entries` | 입차 목록 요청 + 응답 읽는 법 |
| `entries.fields.plate` | **필수.** 차량번호가 들어있는 키 |
| `entries.fields.id` | 입차 건 식별자. 있으면 중복 등록 방지가 정확해진다. |
| `entries.already_when` | 사이트가 "할인 적용됨"을 알려줄 때 그 조건. 있으면 제일 믿을 만한 중복 방지책. |
| `register` | 무료등록 요청. `${entry.id}`, `${entry.plate}` 사용 가능 |
| `notify` | (선택) 등록되면 텔레그램 등으로 알림 |

아이디·비밀번호는 파일에 직접 쓰지 말고 `${PARKING_USER}`처럼 두고 환경변수로 넣는다.
`parking_site.json`과 `.parking_state.json`은 `.gitignore`에 들어 있다.

성공 판정은 `success_contains`(이 문자열이 있어야 성공) / `failure_contains`(있으면 실패)로 잡는다.
로그인 실패해도 HTTP 200을 주는 사이트가 많아서, 이 둘 중 하나는 꼭 넣는 게 좋다.

## 3. 돌려보기

```bash
export PARKING_USER='아이디'
export PARKING_PASS='비밀번호'

python parking_watch.py --config parking_site.json              # 미리보기: 등록은 안 한다
python parking_watch.py --config parking_site.json --commit     # 진짜 등록
python parking_watch.py --config parking_site.json --commit --watch 300   # 5분마다 계속
```

미리보기에서 `[미리보기] 여기서 무료등록을 호출해요: 12가3456` 이 뜨면 대조까지는 맞은 것이다.

## 4. 자동으로 돌리기

`.github/workflows/parking-watch.yml`이 KST 08~22시에 5분마다 돈다. 저장소
**Settings → Secrets and variables → Actions**에 넣을 값:

| Secret | 값 |
| --- | --- |
| `PARKING_CONFIG_JSON` | `parking_site.json` 내용을 통째로 붙여넣기 |
| `PARKING_USER` / `PARKING_PASS` | 사이트 계정 |
| `PARKING_STORE` | (레시피에서 쓴다면) 매장/세대 식별자 |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | (선택) 알림용 |

- secret이 없으면 워크플로는 조용히 건너뛴다. 지금 상태로 두어도 아무 일도 일어나지 않는다.
- 스케줄 워크플로는 **기본 브랜치에서만** 돈다. 브랜치에 있는 동안엔 `workflow_dispatch`로 수동 실행해 확인한다.
- 수동 실행은 기본이 미리보기다. 실제 등록하려면 `commit` 체크를 켠다.
- GitHub 스케줄은 밀릴 때가 있다(몇 분~십여 분). 분 단위로 정확해야 하면 집에 있는 PC나
  라즈베리파이에서 `--watch 60`으로 돌리는 쪽이 낫다.

## 안 되는 경우

| 증상 | 이유 / 대안 |
| --- | --- |
| 로그인에 문자(SMS) 인증·카카오 로그인·캡차가 붙는다 | 요청 흉내로는 못 뚫는다. Playwright로 실제 브라우저를 띄우고 세션 쿠키를 저장해 재사용하는 방식으로 가야 한다. |
| 입차 목록이 화면에만 있고 요청이 안 보인다 | WebSocket이나 서버 렌더링일 수 있다. `Fetch/XHR` 필터를 풀고 `Doc`/`WS`까지 본다. |
| 앱에서만 되고 웹이 없다 | 웹 버전이 없으면 이 방식은 불가. 앱 API를 봐야 하는데 난이도가 확 올라간다. |
| 로그인은 되는데 목록이 비어 있다 | 쿠키 말고 헤더 토큰(`Authorization`)을 쓰는 사이트다. `login.extract`로 토큰을 뽑아 `entries.headers`에 넣는다. |
| 등록은 됐다는데 실제로는 안 된다 | `success_contains`를 응답 본문의 진짜 성공 표시로 바꾼다. 사이트가 실패에도 200을 주는 경우다. |

## 테스트

```bash
python test_parking_watch.py
```

가짜 주차 사이트를 띄워서 로그인 세션·차량번호 대조·중복 등록 방지를 검증한다.
진짜 사이트의 화면이 바뀌는 건 여기서 못 잡으므로, 그때는 레시피를 고치면 된다.
