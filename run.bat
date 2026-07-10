@echo off
REM 로컬 에이전트 대시보드 실행. 더블클릭하면 서버가 뜨고 브라우저가 열린다.
cd /d "%~dp0"

REM psutil 이 없으면 설치 (최초 1회)
python -c "import psutil" 2>nul || python -m pip install psutil

REM 서버를 띄우고 브라우저를 연다
start "" http://127.0.0.1:8787
python server.py
