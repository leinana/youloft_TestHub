@echo off
chcp 65001 >nul
set HOSTS=%SystemRoot%\System32\drivers\etc\hosts

echo 正在添加本地域名映射...

REM 检查是否已存在
findstr /R "testhub.local" "%HOSTS%" >nul 2>&1
if %errorlevel% equ 0 (
    echo testhub.local 已存在，跳过
) else (
    echo. >> "%HOSTS%"
    echo 127.0.0.1 testhub.local >> "%HOSTS%"
    echo 已添加: 127.0.0.1 testhub.local
)

echo.
echo ========================================
echo   配置完成！
echo   现在可以通过以下地址访问:
echo.
echo   http://testhub.local:3000  (域名)
echo   http://localhost:3000      (本地)
echo   http://192.168.8.87:3000   (局域网)
echo   http://127.0.0.1:3000      (本地)
echo.
echo ========================================
pause
