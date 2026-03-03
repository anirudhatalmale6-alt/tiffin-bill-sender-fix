@echo off
echo ============================================
echo  Running TiffinBillSender (fixed version)
echo ============================================
echo.
pip install selenium webdriver-manager >nul 2>&1
python main.py
pause
