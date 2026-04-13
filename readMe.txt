python3 -m venv venv &&  . venv/bin/activate &&  pip install --upgrade pip &&  pip install -r requirements.txt

venv/bin/uvicorn index:app --host 0.0.0.0 --port 8000

