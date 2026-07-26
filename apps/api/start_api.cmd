@echo off
REM Start the API server in the background.
setlocal
call "D:\OutreachOS\Outreach-OS\apps\api\.venv\Scripts\activate.bat"
cd /d "D:\OutreachOS\Outreach-OS\apps\api"
for /f "usebackq tokens=1,2 delims==" %%A in ("..\..\.env") do set %%A=%%B
start "outreach-api" /B python -m uvicorn outreach_os.main:app --host 127.0.0.1 --port 8000 --log-level info > "D:\OutreachOS\Outreach-OS\apps\api\api.log" 2> "D:\OutreachOS\Outreach-OS\apps\api\api.err.log"
endlocal
