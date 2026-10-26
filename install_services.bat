@echo off
chcp 65001 >nul
echo ========================================
echo   TestHub Windows 服务安装
echo ========================================
echo.

REM 刷新 PATH 以包含 nssm
set "PATH=%PATH%;%ProgramFiles%\nssm"

echo [1/3] 安装 Django 后端服务...
nssm stop TestHubBackend >nul 2>&1
nssm remove TestHubBackend confirm >nul 2>&1
nssm install TestHubBackend "C:\Users\Ln\Youloft_Hub111\venv\Scripts\python.exe" "C:\Users\Ln\Youloft_Hub111\manage.py" "runserver" "0.0.0.0:8000"
nssm set TestHubBackend AppDirectory "C:\Users\Ln\Youloft_Hub111"
nssm set TestHubBackend DisplayName "TestHub Django Backend"
nssm set TestHubBackend Description "TestHub AI测试管理平台 - Django后端服务 (端口8000)"
nssm set TestHubBackend Start SERVICE_AUTO_START
nssm set TestHubBackend AppStdout "C:\Users\Ln\Youloft_Hub111\logs\service_django.log"
nssm set TestHubBackend AppStderr "C:\Users\Ln\Youloft_Hub111\logs\service_django_error.log"
echo   Django 后端服务已安装

echo.
echo [2/3] 安装 Celery Worker 服务...
nssm stop TestHubCelery >nul 2>&1
nssm remove TestHubCelery confirm >nul 2>&1
nssm install TestHubCelery "C:\Users\Ln\Youloft_Hub111\venv\Scripts\celery.exe" "-A" "backend" "worker" "--loglevel=info" "--pool=solo"
nssm set TestHubCelery AppDirectory "C:\Users\Ln\Youloft_Hub111"
nssm set TestHubCelery DisplayName "TestHub Celery Worker"
nssm set TestHubCelery Description "TestHub AI测试管理平台 - Celery异步任务服务"
nssm set TestHubCelery Start SERVICE_AUTO_START
nssm set TestHubCelery AppStdout "C:\Users\Ln\Youloft_Hub111\logs\service_celery.log"
nssm set TestHubCelery AppStderr "C:\Users\Ln\Youloft_Hub111\logs\service_celery_error.log"
echo   Celery Worker 服务已安装

echo.
echo [3/3] 启动服务...
nssm start TestHubBackend
nssm start TestHubCelery
echo   服务已启动

echo.
echo ========================================
echo   安装完成！
echo.
echo   服务列表:
echo     TestHubBackend - Django后端 (:8000)
echo     TestHubCelery  - Celery异步任务
echo.
echo   常用命令:
echo     nssm status TestHubBackend   查看状态
echo     nssm restart TestHubBackend  重启服务
echo     nssm stop TestHubBackend     停止服务
echo ========================================
echo.
pause
