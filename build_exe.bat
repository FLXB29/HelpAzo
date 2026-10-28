@echo off
cd /d "%~dp0"
echo Dang build cap_solve_v1.0.24.exe bang PyInstaller...
pyinstaller --onefile --noconsole --name "cap_solve_v1.0.24" ^
    --add-data "prompts;prompts" ^
    --add-data "systemp_prompt.txt;." ^
    main.py
echo Copying exe to root directory...
copy /y "dist\cap_solve_v1.0.24.exe" "cap_solve_v1.0.24.exe"
echo Build thanh cong!
pause
