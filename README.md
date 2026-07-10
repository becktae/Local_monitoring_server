# Agent Mission Control (로컬 전용)

윈도우 PC 한 대에서 도는 감시 대시보드. 세 가지를 우선순위대로 본다.

1. **Job 수행 여부** — 작업 스케줄러의 작업들이 성공했는지, 실패했는지, 미아가 됐는지
2. **AI spend** — ccusage로 집계한 Claude · Gemini · Codex 토큰 비용
3. **리소스** — 메모리 · 스토리지 · CPU

로컬 전용이다. 서버는 `127.0.0.1` 에만 바인딩되어 외부에서 접근할 수 없고, 데이터는 이 PC를 벗어나지 않는다.

## 구성

```
agent-dashboard/
├─ server.py        표준 http.server. / 와 /api/status 두 경로만 제공
├─ collectors.py    스케줄러 / 리소스 / 토큰 수집 로직
├─ dashboard.html   화면. 5초마다 /api/status 를 폴링
├─ run.bat          더블클릭 실행
└─ README.md
```

의존성은 `psutil` 하나뿐이다. 나머지는 파이썬 표준 라이브러리.

## 실행

**필요한 것**: Python 3.9+ (설치 시 "Add to PATH" 체크)

`run.bat` 을 더블클릭하면 끝이다. 최초 1회 psutil 을 자동 설치하고, 서버를 띄운 뒤 브라우저로 `http://127.0.0.1:8787` 을 연다.

수동 실행:

```
pip install psutil
python server.py
```

## 감시할 에이전트 등록하기

`collectors.py` 상단의 `WATCHED_TASKS` 리스트에 **작업 스케줄러의 작업 이름**을 넣으면 된다.

```python
WATCHED_TASKS = [
    "daily-backup",
    "news-scraper",
    "report-gen",
]
```

여기 적은 이름이 스케줄러 조회 결과에 안 나오면 그 작업은 **orphan(미아)** 으로 표시된다. 이게 "미아 에이전트가 없는지 챙긴다"는 목적을 직접 구현한 부분이다.

작업 이름 확인:

```
schtasks /query /fo LIST /v
```

여기 나오는 `TaskName` 의 마지막 `\` 뒤 이름을 그대로 쓰면 된다.

## AI 토큰 비용 (ccusage)

토큰 비용은 [ccusage](https://ccusage.com) 를 호출해 가져온다. Claude · Gemini · Codex 등 감지되는 소스를 한 번에 합산해준다.

ccusage 가 설치돼 있으면 자동으로 실제 값을 읽고, 없으면 목데이터로 폴백한다(대시보드는 그대로 뜬다). 설치:

```
npm install -g ccusage
```

`collectors.py` 는 `ccusage daily --json` 을 호출한다. ccusage 버전에 따라 JSON 구조가 조금 다를 수 있어 방어적으로 파싱하도록 해뒀다. 실제 값이 안 맞으면 아래 명령의 출력을 보고 `_collect_tokens_ccusage()` 의 키를 맞추면 된다.

```
ccusage daily --json
```

## 부팅 시 자동 실행 (선택)

작업 스케줄러에 `run.bat` 을 "로그온 시 실행" 으로 등록하면 PC 켤 때 자동으로 뜬다.
또는 `pythonw server.py` 로 콘솔 창 없이 백그라운드 상주시킬 수 있다.

## 판정 규칙

작업 하나의 상태는 이렇게 정해진다.

- `ok` — 마지막 종료코드 0
- `fail` — 종료코드가 0이 아님
- `orphan` — 다음 실행 예약이 없음(`Next Run Time` 이 비었거나 N/A) 또는 감시 목록에 있는데 스케줄러에 아예 없음
- `idle` — 아직 한 번도 실행되지 않음

`late`(지연)는 예약 시각 대비 실제 시작이 늦은 경우인데, 이건 판정 기준(허용 지연 시간)을 정해야 해서 지금은 목데이터에만 있다. 필요하면 임계값을 정해 추가하면 된다.
