Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "         RETURNLESS - B2B SAAS PLATFORM               " -ForegroundColor Yellow
Write-Host "   Predict Returns. Reduce Costs. Increase Profits.    " -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "Installing/checking AI dependencies (pandas, scikit-learn, joblib)..."
python -m pip install -r requirements.txt --quiet
Write-Host "Starting ReturnLess local server at http://localhost:8000..."
Start-Process "http://localhost:8000"
python server.py
