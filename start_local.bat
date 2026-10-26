@echo off
chcp 65001 >nul
cd /d "C:\Users\Ln\Youloft_Hub111"

echo ========================================
echo   TestHub 本地启动脚本
echo ========================================
echo.

echo [1/5] 启动 MySQL...
set "MYSQL_BIN=C:\Program Files\MySQL\MySQL Server 8.4\bin"
set "MYSQL_DATA=C:\ProgramData\MySQL\MySQL Server 8.4\Data"
set "MYSQL_LOG=C:\Users\Ln\Youloft_Hub111\logs\mysql.log"

"%MYSQL_BIN%\mysqladmin.exe" ping -u root -ptesthub123 >nul 2>&1
if %errorlevel% equ 0 (
    echo   MySQL 已在运行
    goto mysql_ready
)

echo   正在启动 MySQL...
start "" /B "%MYSQL_BIN%\mysqld.exe" --datadir="%MYSQL_DATA%" --port=3306 --log-error="%MYSQL_LOG%"

REM 等待 MySQL 真正就绪（最多 40 秒），避免 Django 连不上数据库
set /a WAIT=0
:wait_mysql
"%MYSQL_BIN%\mysqladmin.exe" ping -u root -ptesthub123 >nul 2>&1
if %errorlevel% equ 0 goto mysql_ready
set /a WAIT+=1
if %WAIT% geq 40 goto mysql_timeout
timeout /t 1 /nobreak >nul
goto wait_mysql

:mysql_timeout
echo   [错误] MySQL 启动超时（40秒），请检查 logs\mysql.log
pause
exit /b 1

:mysql_ready
echo   MySQL 已就绪

echo.
echo [2/5] 启动 Redis...
sc query Redis 2>nul | findstr /i "RUNNING" >nul
if %errorlevel% equ 0 (
    echo   Redis 已在运行
) else (
    start "" /B "C:\Program Files\Redis\redis-server.exe"
    timeout /t 2 /nobreak >nul
    echo   Redis 已启动
)

echo.
echo [3/5] 启动 Django 后端 (端口 8000)...
start "Django Backend" cmd /c "cd /d C:\Users\Ln\Youloft_Hub111 && call venv\Scripts\activate.bat && python manage.py runserver 0.0.0.0:8000"
set /a WAIT=0
:wait_django
netstat -ano | findstr /R ":8000[^0-9]" | findstr /i "LISTEN" >nul 2>&1
if %errorlevel% equ 0 goto django_ok
set /a WAIT+=1
if %WAIT% geq 30 goto django_fail
timeout /t 1 /nobreak >nul
goto wait_django

:django_fail
echo   [错误] Django 未在 8000 端口就绪（30秒），请查看弹出的 Django 窗口或 logs\service_django_error.log
pause
exit /b 1

:django_ok
echo   Django 后端已就绪 (端口 8000)

echo.
echo [4/5] 启动 Celery Worker...
start "Celery Worker" cmd /c "cd /d C:\Users\Ln\Youloft_Hub111 && call venv\Scripts\activate.bat && celery -A backend worker --loglevel=info --pool=solo"
timeout /t 2 /nobreak >nul
echo   Celery Worker 已启动

echo.
echo [4.5/5] 启动 Celery Beat（定时任务：清理采集快照）...
start "Celery Beat" cmd /c "cd /d C:\Users\Ln\Youloft_Hub111 && call venv\Scripts\activate.bat && celery -A backend beat --loglevel=info"
timeout /t 2 /nobreak >nul
echo   Celery Beat 已启动

echo.
echo [5/5] 启动 Vue 前端 (端口 3000)...
start "Vue Frontend" cmd /c "cd /d C:\Users\Ln\Youloft_Hub111\frontend && npm run dev"
set /a WAIT=0
:wait_vue
netstat -ano | findstr /R ":3000[^0-9]" | findstr /i "LISTEN" >nul 2>&1
if %errorlevel% equ 0 goto vue_ok
set /a WAIT+=1
if %WAIT% geq 60 goto vue_fail
timeout /t 1 /nobreak >nul
goto wait_vue

:vue_fail
echo   [错误] Vue 未在 3000 端口就绪（60秒），请查看弹出的 Vue 窗口
pause
exit /b 1

:vue_ok
echo   Vue 前端已就绪 (端口 3000)

echo.
echo ========================================
echo   全部服务启动完成!
echo ========================================
echo.
echo   前端页面 : http://localhost:3000
echo   后端 API : http://localhost:8000
echo   API 文档 : http://localhost:8000/api/docs/
echo   Admin 后台: http://localhost:8000/admin/
echo.
echo   超级用户 : admin / admin123
echo.
echo   说明：关闭弹出的命令行窗口即停止对应服务
echo.
pause
