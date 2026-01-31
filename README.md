# jacpae_api (FASE 0)

Bootstrap de la API (FastAPI) — fase 0

Instrucciones rápidas (Windows PowerShell):

1. Crear entorno virtual:
   python -m venv .venv
   .\.venv\Scripts\Activate

2. Instalar dependencias:
   pip install -r requirements.txt

3. Levantar servidor:
   uvicorn --app-dir src app.main:app --reload --host 0.0.0.0 --port 8000

4. Verificar:
   curl http://127.0.0.1:8000/health
