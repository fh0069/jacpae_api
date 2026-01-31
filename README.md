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

5. Readiness y logging (validaciones manuales):
   - Health público (barato):
     curl -i http://127.0.0.1:8000/health
     -> 200 OK, body: {"status":"ok"}

   - Readiness (verifica JWKS si está configurada):
     curl -i http://127.0.0.1:8000/health/ready
     -> 200 OK, body: {"status":"ok","checks":{"jwks":"ok"}} (si JWKS accesible)
     -> 503 Service Unavailable, body: {"status":"fail","checks":{"jwks":"unreachable"},"detail":"JWKS unreachable"} (si JWKS inalcanzable)
     Para forzar fallo localmente:
       PowerShell: $env:SUPABASE_JWKS_URL = "http://127.0.0.1:9999/.well-known/jwks.json"; Restart server

   - Request ID y logging estructurado:
     - Envío de header opcional: curl -i -H "X-Request-ID: abc" http://127.0.0.1:8000/health
       -> Responderá con header `X-Request-ID: abc` (si lo mandas) o generará uno nuevo.
     - Observa la terminal donde corre uvicorn: verás logs JSON con claves `request_id`, `path`, `method`, `status_code`, `latency_ms`.

6. Para pruebas unitarias:
   pytest -q
