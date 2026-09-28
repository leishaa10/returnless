@echo off
title ReturnLess - AI Return Prediction Platform
echo =======================================================
echo          RETURNLESS - B2B SAAS PLATFORM
echo    Predict Returns. Reduce Costs. Increase Profits.
echo =======================================================
echo.
echo Installing/checking AI dependencies (pandas, scikit-learn, joblib)...
python -m pip install -r requirements.txt --quiet
echo Starting ReturnLess local server...
start http://localhost:8000
python server.py
pause
