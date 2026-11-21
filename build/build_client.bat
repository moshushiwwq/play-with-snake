@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
python build\release.py --client
if errorlevel 1 goto :err
echo.
echo 客户端单文件 exe 已输出：release\PlayWithSnake-Client.exe
echo 构建日志：build\logs\
exit /b 0
:err
echo 构建失败，请查看 build\logs\ 下的最新日志
exit /b 1
