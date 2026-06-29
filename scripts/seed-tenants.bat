@echo off
REM Windows wrapper for seed-tenants.py
setlocal
pushd "%~dp0\.."
python scripts\seed-tenants.py
popd
endlocal
