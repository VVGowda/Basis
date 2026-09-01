# Start Basis on http://localhost:8767
if (-not (Test-Path "venv")) {
    python -m venv venv
    venv\Scripts\python.exe -m pip install -r requirements.txt
}
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8767
