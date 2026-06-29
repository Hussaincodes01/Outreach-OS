@echo off
REM Start the API server in the background.
setlocal
call "D:\SaaS Lead\apps\api\.venv\Scripts\activate.bat"
cd /d "D:\SaaS Lead\apps\api"
for /f "usebackq tokens=1,2 delims==" %%A in (".env") do set %%A=%%B
start "outreach-api" /B python -m uvicorn outreach_os.main:app --host 127.0.0.1 --port 8000 --log-level info > "D:\SaaS Lead\apps\api\api.log" 2> "D:\SaaS Lead\apps\api\api.err.log"
endlocal
