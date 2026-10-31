@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
python build\sync_version.py || goto :err
python build\make_icon.py || goto :err
python -m PyInstaller build\server.spec --noconfirm --clean --distpath build\dist --workpath build\work || goto :err
echo.
echo 服务端已构建：build\dist\PlayWithSnake-Server
exit /b 0
:err
echo 构建失败
exit /b 1
