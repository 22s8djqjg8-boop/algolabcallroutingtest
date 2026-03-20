@echo off
echo ============================================
echo  LGU+ Centrex ActiveX 등록
echo  (관리자 권한으로 실행해주세요)
echo ============================================
echo.

:: CAB 파일에서 OCX 추출 및 등록
:: CAB 파일이 같은 폴더에 있어야 합니다

set CABFILE=LGUBaseOpenApi_1.0.1.21.cab

if not exist "%CABFILE%" (
    echo [오류] %CABFILE% 파일을 찾을 수 없습니다.
    echo 이 BAT 파일과 같은 폴더에 CAB 파일을 넣어주세요.
    pause
    exit /b 1
)

echo CAB 파일에서 OCX 추출 중...
expand "%CABFILE%" -F:*.ocx . >nul 2>&1
expand "%CABFILE%" -F:*.dll . >nul 2>&1

:: OCX 파일 찾기
set OCXFILE=
for %%f in (*.ocx) do set OCXFILE=%%f
for %%f in (LGUBaseOpenApi*.dll) do if "!OCXFILE!"=="" set OCXFILE=%%f

if "%OCXFILE%"=="" (
    echo [오류] OCX 파일을 찾을 수 없습니다.
    echo CAB 내용물을 확인합니다...
    expand "%CABFILE%" -D
    pause
    exit /b 1
)

echo OCX 파일 발견: %OCXFILE%
echo 등록 중...
regsvr32 /s "%CD%\%OCXFILE%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo  ActiveX 등록 성공!
    echo  이제 centrex_phone.pyw 를 실행하세요.
    echo ============================================
) else (
    echo.
    echo [오류] 등록 실패. 관리자 권한으로 다시 실행해주세요.
    echo 방법: 이 파일을 우클릭 ^> 관리자 권한으로 실행
)

echo.
pause
