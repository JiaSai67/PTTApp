@echo off
chcp 65001 >nul
set CWD=%~dp0
if "%CWD:~-1%"=="\" set CWD=%CWD:~0,-1%

:: Define Project Name and Description here
set PROJECT_NAME=按鍵發話控制器 (PTTApp)
set PROJECT_DESC=針對任意程式設定麥克風按鍵發話快捷鍵
set EXEC_FILE=%CWD%\main.py

echo Registering "%PROJECT_NAME%" to AI Tool Launcher...
python g:\python\toolLauncher\register_api.py --name "%PROJECT_NAME%" --desc "%PROJECT_DESC%" --exec "%EXEC_FILE%" --cwd "%CWD%"

echo.
echo Registration complete! You can now close this window.
pause
