@echo off
chcp 65001 >nul
rem Inject Monitor launcher (Windows): runs monitor.py inside WSL.
rem Adjust the path if you installed the monitor elsewhere (default ~/inject-monitor).
wsl sh -lc "python3 ~/inject-monitor/monitor.py --port 8092"
pause
