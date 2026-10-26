@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   TestHub Docker 一键部署
echo ========================================
echo.

echo [1/3] 检查 Docker 环境...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [错误] Docker 未安装或未启动！
    echo   请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)
echo   Docker 已就绪

echo.
echo [2/3] 构建并启动所有服务...
echo   这可能需要 10-20 分钟（首次构建镜像）
echo   服务包括: MySQL, Redis, Django后端, Celery, Vue前端
echo.

docker compose up -d --build

if %errorlevel% neq 0 (
    echo.
    echo   [错误] 启动失败，请查看上方错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 等待服务就绪...
echo   正在等待后端启动（约30秒）...

REM 等待后端服务就绪
for /l %%i in (1,1,30) do (
    curl -s http://localhost:8000/api/docs/ >nul 2>&1
    if !errorlevel! equ 0 goto :services_ready
    timeout /t 2 /nobreak >nul
)

:services_ready
echo.
echo ========================================
echo   部署完成！
echo ========================================
echo.
echo   前端页面 : http://localhost:3000
echo   后端 API : http://localhost:8000
echo   API 文档 : http://localhost:8000/api/docs/
echo   Admin 后台: http://localhost:8000/admin/
echo.
echo   超级用户 : admin / admin123
echo.
echo ========================================
echo   常用命令:
echo   查看日志 : docker compose logs -f
echo   停止服务 : docker compose down
echo   重启服务 : docker compose restart
echo ========================================
echo.
pause
