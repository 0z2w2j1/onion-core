@echo off
REM Onion Core Load Test Script using hey
REM 
REM Usage:
REM     scripts\load_test.bat http://localhost:8000/chat
REM
REM Requirements:
REM     go install github.com/rakyll/hey@latest
REM     Add %USERPROFILE%\go\bin to PATH

setlocal

set BASE_URL=%1
if "%BASE_URL%"=="" set BASE_URL=http://localhost:8000/chat

set BODY={"messages":[{"role":"user","content":"Hello"}]}

echo ========================================
echo Onion Core Load Test
echo Base URL: %BASE_URL%
echo ========================================
echo.

REM Test different QPS levels
for %%q in (100 1000 5000) do (
    echo --- Testing %%q QPS ---
    hey -n 100000 -q %%q -m POST -H "Content-Type: application/json" -d "%BODY%" %BASE_URL%
    echo.
    echo.
)

echo ========================================
echo Load test complete
echo ========================================

endlocal