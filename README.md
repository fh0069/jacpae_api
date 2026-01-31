# jacpae_api (FASE 0/1)

Bootstrap de la API (FastAPI) — fase 0 y preparación para Fase 1 (Auth)

Variables de entorno relevantes (ejemplo en `.env.example`):
- SUPABASE_URL
- SUPABASE_ISS
- SUPABASE_JWKS_URL
- SUPABASE_AUD
- JWKS_CACHE_TTL

Instrucciones rápidas (Windows PowerShell):

1. Crear entorno virtual:
   python -m venv .venv
   .\.venv\Scripts\Activate

2. Instalar dependencias:
   pip install -r requirements.txt

3. Levantar servidor:
   .\.venv\Scripts\python -m uvicorn --app-dir src app.main:app --host 0.0.0.0 --port 8000

4. Verificar:
   curl http://127.0.0.1:8000/health

5. Para pruebas unitarias:
   pytest -q
