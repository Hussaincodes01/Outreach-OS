@echo off
cd /d "D:\SaaS Lead\apps\web"
call npm run dev > "D:\SaaS Lead\apps\web\web.log" 2> "D:\SaaS Lead\apps\web\web.err.log"
