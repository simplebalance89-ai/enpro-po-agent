$env:PYTHONPATH = "$PSScriptRoot\src;$env:PYTHONPATH"
uvicorn src.server:app --host 0.0.0.0 --port 3000
