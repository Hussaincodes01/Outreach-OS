@echo off
cd /d "D:\OutreachOS\Outreach-OS\apps\web"
call npm run dev > "D:\OutreachOS\Outreach-OS\apps\web\web.log" 2> "D:\OutreachOS\Outreach-OS\apps\web\web.err.log"
