Command to run on the currently used server:
```bash
sudo -E venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 443 --ssl-certfile cert.pem --ssl-keyfile private.key
```
