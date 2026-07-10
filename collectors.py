"""로컬 상태 수집기. 스케줄러 / 시스템 리소스 / AI 토큰 세 가지를 모은다.

로컬 전용. 확장 고려 없음. 표준 라이브러리 + psutil 만 사용한다.
"""
import subprocess
import platform
import json
import shutil
from datetime import datetime

IS_WINDOWS = platform.system() == "Windows"

# 감시할 에이전트(윈도우 작업 스케줄러의 작업 이름).
# 여기 이름만 채워 넣으면 대시보드가 그 작업들을 추적한다.
WATCHED_TASKS = [
    "daily-backup",
    "news-scraper",
    "report-gen",
    "db-vacuum",
    "mail-digest",
    "metrics-agent",
]

# 예약이 사라졌는데도 감시하고 싶은(=미아 후보) 작업.
# WATCHED_TASKS 에는 있지만 schtasks 결과에 안 나오면 orphan 으로 본다.


def _run(cmd):
    """명령을 돌려 stdout 을 준다. 실패하면 빈 문자열."""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        return out.stdout or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 1. 스케줄러 (최우선)
# ---------------------------------------------------------------------------

def collect_scheduler():
    """윈도우 작업 스케줄러에서 감시 대상 작업의 상태를 읽는다.

    반환: 작업 리스트. 각 항목은
      name, status(ok|fail|late|orphan|idle), last_run, next_run, last_result(exit code)
    """
    if IS_WINDOWS:
        rows = _collect_scheduler_windows()
    else:
        rows = _collect_scheduler_mock()

    ok = sum(1 for r in rows if r["status"] == "ok")
    total = len(rows)
    failed = sum(1 for r in rows if r["status"] == "fail")
    orphaned = sum(1 for r in rows if r["status"] == "orphan")
    return {
        "agents": rows,
        "summary": {"ok": ok, "total": total, "failed": failed, "orphaned": orphaned},
        "swept_at": datetime.now().strftime("%H:%M:%S"),
    }


def _collect_scheduler_windows():
    """schtasks /query /fo LIST /v 를 파싱한다."""
    raw = _run(["schtasks", "/query", "/fo", "LIST", "/v"])
    # LIST 포맷은 작업마다 빈 줄로 구분된 key:value 블록.
    blocks, cur = [], {}
    for line in raw.splitlines():
        if not line.strip():
            if cur:
                blocks.append(cur)
                cur = {}
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            cur[k.strip()] = v.strip()
    if cur:
        blocks.append(cur)

    # TaskName 은 보통 "\\news-scraper" 형태. 이름만 뽑아 매칭한다.
    found = {}
    for b in blocks:
        tn = b.get("TaskName", "")
        short = tn.split("\\")[-1]
        if short in WATCHED_TASKS:
            found[short] = b

    rows = []
    for name in WATCHED_TASKS:
        b = found.get(name)
        if b is None:
            # 감시 대상인데 스케줄러에 없다 → 미아
            rows.append({
                "name": name, "status": "orphan",
                "last_run": "-", "next_run": "none", "last_result": None,
                "detail": "예약이 스케줄러에 없음",
            })
            continue

        last_run = b.get("Last Run Time", "").strip()
        next_run = b.get("Next Run Time", "").strip()
        result_raw = b.get("Last Result", "").strip()
        try:
            code = int(result_raw)
        except ValueError:
            code = None

        # 상태 판정: 종료코드 0 이면 성공, 그 외엔 실패.
        # next_run 이 비어있거나 N/A 면 예약 소실(orphan) 로 본다.
        if next_run in ("", "N/A", "해당 없음"):
            status = "orphan"
        elif code == 0:
            status = "ok"
        elif code is None:
            status = "idle"
        else:
            status = "fail"

        rows.append({
            "name": name, "status": status,
            "last_run": last_run, "next_run": next_run,
            "last_result": code,
            "detail": f"exit {code}" if code is not None else "미실행",
        })
    return rows


def _collect_scheduler_mock():
    """윈도우가 아닌 환경(개발/검증)용 목데이터."""
    return [
        {"name": "daily-backup", "status": "ok",    "last_run": "오늘 02:00", "next_run": "내일 02:00", "last_result": 0, "detail": "exit 0 · ran 03m12s"},
        {"name": "news-scraper", "status": "ok",    "last_run": "오늘 08:00", "next_run": "14:00",      "last_result": 0, "detail": "exit 0 · ran 00m47s"},
        {"name": "report-gen",   "status": "fail",  "last_run": "오늘 09:30", "next_run": "내일 09:30", "last_result": 1, "detail": "exit 1 · traceback"},
        {"name": "db-vacuum",    "status": "ok",    "last_run": "오늘 04:00", "next_run": "일 04:00",   "last_result": 0, "detail": "exit 0 · weekly"},
        {"name": "mail-digest",  "status": "late",  "last_run": "오늘 08:22", "next_run": "내일 07:00", "last_result": 0, "detail": "started 1h22m 지연"},
        {"name": "metrics-agent","status": "orphan","last_run": "어제 18:00", "next_run": "none",       "last_result": None, "detail": "20h 무응답 · 예약 사라짐"},
    ]


# ---------------------------------------------------------------------------
# 2. AI 토큰 비용 (차우선)
# ---------------------------------------------------------------------------

def collect_tokens():
    """ccusage 로 오늘/이번 달 토큰 비용을 읽는다.

    ccusage 가 없으면 목데이터로 폴백한다.
    """
    if shutil.which("ccusage") or shutil.which("npx"):
        data = _collect_tokens_ccusage()
        if data:
            return data
    return _collect_tokens_mock()


def _collect_tokens_ccusage():
    """`ccusage daily --json` 결과를 소스별로 합산한다.

    ccusage 는 Claude·Gemini·Codex 등 감지된 모든 소스를 한 리포트에 넣어준다.
    출력 구조가 버전마다 조금씩 다르므로, 방어적으로 파싱한다.
    """
    cmd = ["ccusage", "daily", "--json"] if shutil.which("ccusage") \
        else ["npx", "ccusage", "daily", "--json"]
    raw = _run(cmd)
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # daily 리포트는 보통 {"daily": [ {date, ...cost/models}, ... ]} 형태.
    days = parsed.get("daily") or parsed.get("data") or []
    if not days:
        return None

    today = days[-1]  # 마지막 항목을 오늘로 간주
    total_today = float(today.get("totalCost") or today.get("cost") or 0.0)
    month_total = sum(float(d.get("totalCost") or d.get("cost") or 0.0) for d in days)

    # 소스(모델 provider)별 분해가 있으면 쓰고, 없으면 total 만 보여준다.
    sources = []
    breakdown = today.get("breakdown") or today.get("models") or []
    for item in breakdown:
        sources.append({
            "name": item.get("name") or item.get("model") or "?",
            "cost": float(item.get("cost") or item.get("totalCost") or 0.0),
            "tokens": int(item.get("totalTokens") or item.get("tokens") or 0),
        })

    # 최근 7일 스파크라인 값
    spark = [round(float(d.get("totalCost") or d.get("cost") or 0.0), 2) for d in days[-7:]]

    return {
        "today_total": round(total_today, 2),
        "month_total": round(month_total, 2),
        "sources": sources,
        "spark": spark,
        "source": "ccusage",
    }


def _collect_tokens_mock():
    return {
        "today_total": 8.42,
        "month_total": 187.30,
        "sources": [
            {"name": "claude", "cost": 4.87, "tokens": 1240000},
            {"name": "gemini", "cost": 2.11, "tokens": 890000},
            {"name": "codex",  "cost": 1.44, "tokens": 402000},
        ],
        "spark": [3.4, 5.2, 3.0, 6.5, 4.6, 8.0, 5.9],
        "source": "mock",
    }


# ---------------------------------------------------------------------------
# 3. 시스템 리소스 (마지막)
# ---------------------------------------------------------------------------

def collect_resources():
    """psutil 로 메모리·디스크·CPU 를 읽는다."""
    import psutil

    vm = psutil.virtual_memory()
    mem = {
        "percent": vm.percent,
        "used_gb": round(vm.used / 1024**3, 1),
        "total_gb": round(vm.total / 1024**3, 1),
    }

    disks = []
    for part in psutil.disk_partitions(all=False):
        # 광학/네트워크 드라이브 등에서 접근 오류가 날 수 있어 감싼다.
        try:
            u = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append({
            "mount": part.mountpoint,
            "percent": u.percent,
            "used_gb": round(u.used / 1024**3, 0),
            "total_gb": round(u.total / 1024**3, 0),
        })

    cpu = psutil.cpu_percent(interval=0.3)
    return {"mem": mem, "disks": disks, "cpu": cpu, "cores": psutil.cpu_count()}


# ---------------------------------------------------------------------------

def collect_all():
    """대시보드가 한 번에 받아가는 전체 상태."""
    return {
        "scheduler": collect_scheduler(),
        "tokens": collect_tokens(),
        "resources": collect_resources(),
        "host": platform.node(),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    print(json.dumps(collect_all(), ensure_ascii=False, indent=2))
