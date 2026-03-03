@echo off
echo ============================================
echo  Building TiffinBillSender.exe (fixed)
echo ============================================
echo.
echo Installing dependencies...
pip install selenium webdriver-manager pyinstaller
echo.
echo Building .exe ...
pyinstaller --onefile --name TiffinBillSender --clean --noconfirm main.py
echo.
echo Done! Your fixed .exe is in the "dist" folder.
echo Copy dist\TiffinBillSender.exe to your original folder.
pause
