# jacpae_api

API REST desarrollada con FastAPI. Proporciona acceso autenticado a facturas en PDF,
gestiona notificaciones internas de tipo giro, reparto y oferta, sirve el PDF de la
oferta comercial activa, expone el libro mayor financiero del cliente y el listado fiscal
de IVA sobre facturas emitidas. Está diseñada para ser consumida por una aplicación móvil Flutter.

Incluye envío de notificaciones push vía FCM como señal de activación (wake-up). El push es una capacidad degradable: si Firebase no está configurado, la API arranca y los jobs siguen funcionando sin error.

---

## Arquitectura

### Componentes

```
Aplicación cliente (Flutter)
        |
        | HTTPS  Authorization: Bearer <JWT>
        v
+-------------------+
|   jacpae_api      |  FastAPI + Uvicorn — Windows Server
+-------------------+
     |      |              |
     v      v              v
MariaDB  MariaDB       Supabase (PostgREST)
ventas   contabilidad  customer_profiles
(g4)     (g4finan)     notifications
     |
     v
NAS / Filesystem
PDFs facturas + ofertas
```

| Componente | Función |
|---|---|
| MariaDB ventas (`MARIADB_DB`) | Facturas (`cab_venta`, `pie_venta_e`), rutas de reparto (`rutas_programacion`, `lin_rutas_grupo`, `cliente`) |
| MariaDB contabilidad (`MARIADB_FINAN_DB`) | Giros/vencimientos (`efectos_e`). Mismo host y credenciales que ventas, schema diferente |
| Supabase Auth + JWKS | Emisión de JWT y endpoint de claves públicas para verificación de firma |
| Supabase PostgREST | Lectura de `customer_profiles`; escritura y lectura de `notifications` |
| NAS / Filesystem | Almacenamiento de PDFs de facturas y ofertas |

### Flujo de autenticación

1. El cliente envía `Authorization: Bearer <JWT>` en cada petición protegida.
2. El backend extrae el `kid` del header JWT sin verificar la firma todavía.
3. Resuelve la clave pública desde `SUPABASE_JWKS_URL` con caché configurable (`JWKS_CACHE_TTL`).
4. Verifica firma, `aud` (`SUPABASE_AUD`) e `iss` (`SUPABASE_ISS`).
   Algoritmos aceptados: `RS256`, `ES256`, `ES384`, `ES512`.
5. Extrae el `sub` (UUID del usuario) del payload verificado.
6. Para endpoints que requieren perfil de cliente, consulta `customer_profiles` en Supabase
   usando `SUPABASE_SERVICE_ROLE_KEY` (bypasea RLS) y filtra por `user_id`.

### Pools de conexión MariaDB

| Pool | Getter | Schema | minsize / maxsize | Usado por |
|---|---|---|---|---|
| Ventas | `get_pool()` | `MARIADB_DB` | 1 / 10 | Facturas, reparto |
| Contabilidad | `get_pool_finan()` | `MARIADB_FINAN_DB` | 1 / 5 | Giros, ledger financiero, listado VAT |

Los pools se crean en el primer uso y se cierran en el shutdown del servidor.

---

## Endpoints REST

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/health` | No | Liveness check. Siempre `200 {"status":"ok"}`. Sin dependencias externas. |
| GET | `/health/ready` | No | Readiness check. Verifica DB (SELECT 1) y JWKS. `503` si alguno falla. |
| GET | `/me` | JWT | Devuelve claims del token: `sub`, `email`, `role`, `aal`. |
| GET | `/invoices` | JWT | Lista facturas del ejercicio actual y anterior. Params: `limit` (1–200, def. 50), `offset` (≥0, def. 0). |
| GET | `/invoices/{invoice_id}/pdf` | JWT | Descarga el PDF de una factura. Ver contrato más abajo. |
| GET | `/offers/current` | JWT | Descarga el PDF de la oferta activa. `404` si no hay ninguna. |
| GET | `/notifications` | JWT | Lista notificaciones del usuario autenticado, ordenadas por `created_at DESC`. Params: `limit` (1–100, def. 50), `offset`. |
| PATCH | `/notifications/{notification_id}/read` | JWT | Marca una notificación como leída. `204` OK, `404` no encontrada. |
| POST | `/push/register` | JWT | Registra o reactiva un token FCM del dispositivo del usuario autenticado. |
| GET | `/finance/ledger` | JWT | Movimientos contables del cliente con saldo acumulado arrastrado. Params: `start_date`, `end_date` (ISO 8601). |
| GET | `/invoices/vat-list` | JWT | Listado fiscal de facturas emitidas del cliente con totales agregados. Params: `start_date`, `end_date` (ISO 8601). |

Los endpoints de debug (`/debug/*`) solo se registran cuando `APP_ENV=development`.

### Contrato de `GET /invoices`

Respuesta `200` (array):

```json
[
  {
    "invoice_id": "<base64url>",
    "factura": "FA-000123",
    "fecha": "2025-11-15",
    "base_imponible": 1200.00,
    "importe_iva": 252.00,
    "importe_total": 1452.00
  }
]
```

`invoice_id` es un token opaco `base64url` que codifica internamente los campos clave del
ERP (`ejercicio|clave|documento|serie|numero`). El cliente no interpreta su contenido; lo
pasa directamente a `GET /invoices/{invoice_id}/pdf`. El `clt_prov` nunca se acepta como
parámetro del cliente: se resuelve siempre desde `customer_profiles` usando el `user_id`
del JWT.

### Contrato de `GET /invoices/{invoice_id}/pdf`

| Código | Condición |
|---|---|
| `200` | PDF servido como `application/pdf` con `Content-Disposition: inline` |
| `400` | `invoice_id` no decodificable |
| `401` | Token JWT ausente, expirado o con firma inválida |
| `403` | La factura existe pero pertenece a otro cliente |
| `404` | La factura no existe en la base de datos |
| `409` | La factura existe en DB pero el PDF no se ha generado aún en el NAS |
| `500` | Error interno de base de datos |
| `503` | Supabase no disponible al resolver el perfil del cliente |

La ruta del PDF se construye exclusivamente en el backend. El cliente nunca envía ni
recibe rutas del sistema de archivos.

### Contrato de `GET /notifications`

Respuesta `200` (array):

```json
[
  {
    "id": "uuid",
    "type": "giro",
    "title": "Giro pendiente",
    "body": "El efecto R001 por importe de 1500.00 € vence el 25/02/2026.",
    "data": {
      "cta_contable": "430000962",
      "num_efecto": "R001",
      "vencimiento": "2026-02-25",
      "importe": 1500.0
    },
    "read_at": null,
    "created_at": "2026-02-18T08:00:00+00:00"
  }
]
```

### Contrato de `GET /finance/ledger`

Parámetros de query: `start_date` y `end_date` (formato ISO 8601, ej. `2025-01-01`).

El backend resuelve `customer_profiles.cta_contable` desde el JWT (nunca se acepta como
parámetro del cliente). Calcula el saldo acumulado desde el inicio del ejercicio
correspondiente a `start_date`. Devuelve únicamente los movimientos dentro del rango
`[start_date, end_date]`, con el saldo correcto ya arrastrado en cada línea.

Respuesta `200` (objeto):

```json
{
  "saldo_inicial": 1500.00,
  "movimientos": [
    {
      "fecha": "2025-03-01",
      "concepto": "Fra. FA-000123",
      "debe": 1452.00,
      "haber": 0.00,
      "saldo": 2952.00
    }
  ]
}
```

| Código | Condición |
|---|---|
| `200` | Respuesta con saldo y movimientos |
| `401` | Token JWT ausente, expirado o con firma inválida |
| `403` | Perfil no existe o `is_active=false` |
| `503` | Supabase no disponible al resolver el perfil o MariaDB no disponible |

### Contrato de `GET /invoices/vat-list`

Parámetros de query: `start_date` y `end_date` (formato ISO 8601).

El backend resuelve `customer_profiles.cta_contable` desde el JWT. Devuelve el listado
fiscal de facturas emitidas del cliente en el rango indicado.

Respuesta `200` (objeto):

```json
{
  "items": [
    {
      "fecha_fra": "2025-03-01",
      "num_fra": "FA-000123",
      "base_imp": 1200.00,
      "tipo_iva": 21.0,
      "cuota_iva": 252.00,
      "tipo_recargo": 0.0,
      "cuota_recargo": 0.00,
      "imp_total": 1452.00
    }
  ],
  "totals": {
    "total_base": 1200.00,
    "total_iva": 252.00,
    "total_recargo": 0.00,
    "total_factura": 1452.00
  }
}
```

| Código | Condición |
|---|---|
| `200` | Respuesta con items y totals |
| `401` | Token JWT ausente, expirado o con firma inválida |
| `403` | Perfil no existe o `is_active=false` |
| `503` | Supabase no disponible al resolver el perfil o MariaDB no disponible |

---

## Jobs programados

Los jobs se gestionan con APScheduler (`AsyncIOScheduler`). Todos están deshabilitados
por defecto. El scheduler solo se instancia si al menos un job está habilitado.

| Job | Flag de activación | Horario por defecto | Timezone |
|---|---|---|---|
| `giro_job_daily` | `GIRO_JOB_ENABLED=true` | 08:00 | Europe/Madrid |
| `reparto_job_daily` | `REPARTO_JOB_ENABLED=true` | 08:00 | Europe/Madrid |
| `offer_job_daily` | `OFFER_JOB_ENABLED=true` | 08:05 | Europe/Madrid |

### giro_job_daily

Lee de `customer_profiles` (Supabase) los perfiles con `is_active=true`, `avisar_giro=true`
y `cta_contable` informado. Para cada perfil consulta la tabla `efectos_e` en MariaDB
contabilidad y obtiene los giros con vencimiento en la ventana `[hoy, hoy + N días]`.
`N` es `dias_aviso_giro` del perfil o `GIRO_DEFAULT_DIAS_AVISO` si no está configurado.
Inserta una notificación por giro con deduplicación mediante `source_key`.

### reparto_job_daily

Lee de `customer_profiles` los perfiles con `is_active=true`, `avisar_reparto=true`
y `erp_clt_prov` informado. Calcula la fecha objetivo sumando `N` días laborables
(lunes a viernes; sin festivos) a la fecha actual, donde `N` es `dias_aviso_reparto` del
perfil o `REPARTO_DEFAULT_DIAS_AVISO`. Consulta rutas programadas en MariaDB ventas y
genera una notificación por cada coincidencia, con deduplicación.

### offer_job_daily

Escanea el directorio `{PDF_BASE_DIR}/offers/` buscando archivos `oferta_YYYYMMDD.pdf`
cuya fecha de expiración sea igual o posterior a hoy. Si existe al menos una oferta activa,
inserta una notificación para todos los usuarios con `is_active=true`. Si hay varias ofertas
activas simultáneamente se usa la de expiración más próxima.

### Ejecución manual de un job

```bash
# Con el entorno virtual activo, desde la raíz del proyecto:
.venv\Scripts\python -c "
import asyncio
from src.app.jobs.giro_job import run_giro_job
print(asyncio.run(run_giro_job()))
"
```

Sustituir `giro_job` / `run_giro_job` por `reparto_job` / `run_reparto_job` u
`offer_job` / `run_offer_job` según corresponda.

---

## Sistema de notificaciones

### Tabla `notifications` (Supabase)

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | uuid | Clave primaria, generada automáticamente |
| `user_id` | uuid | Identificador del usuario (coincide con `sub` del JWT) |
| `type` | text | Tipo: `giro`, `reparto` o `oferta` |
| `title` | text | Título de la notificación |
| `body` | text | Cuerpo (nullable) |
| `data` | jsonb | Payload adicional específico por tipo |
| `source_key` | text | Clave de deduplicación — índice UNIQUE `uix_notifications_source_key` |
| `created_at` | timestamptz | Generado automáticamente al insertar |
| `read_at` | timestamptz | Null hasta que el usuario la marca como leída |

El backend trata un `409 Conflict` de PostgREST (violación de unicidad en `source_key`)
como deduplicación, no como error.

### Formato de `source_key` por tipo

| Tipo | Formato |
|---|---|
| `giro` | `giro:{cta_contable}:{num_efecto}:{vencimiento YYYY-MM-DD}` |
| `reparto` | `reparto:{clt_prov}:{ruta}:{subruta}:{fecha YYYY-MM-DD}` |
| `oferta` | `oferta:{expiry YYYY-MM-DD}` |

---

## Push FCM

### Modo degradado

Si `FIREBASE_CREDENTIALS_PATH` o `FIREBASE_PROJECT_ID` no están configurados, el push
queda silenciosamente desactivado. Los jobs siguen ejecutándose y las notificaciones se
persisten en Supabase con normalidad. Se emite un único WARNING en los logs al primer
intento de envío; las llamadas siguientes no emiten warning adicional.

### Tabla `push_devices` (Supabase)

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | uuid | Clave primaria, generada automáticamente |
| `user_id` | uuid | Identificador del usuario (coincide con `sub` del JWT) |
| `device_token` | text UNIQUE | Token FCM del dispositivo |
| `platform` | text | `android` o `ios` |
| `is_active` | bool | `false` = token desactivado por FCM. No se borra. |
| `created_at` | timestamptz | Generado automáticamente al insertar |
| `updated_at` | timestamptz | Actualizado al reactivar un token existente |

### Tokens inválidos

Cuando FCM responde con `UNREGISTERED` o `INVALID_ARGUMENT`, el token se marca
`is_active=false` en `push_devices`. No se elimina. Se mantiene trazabilidad. El
dispositivo puede registrar un nuevo token en cualquier momento vía `POST /push/register`.

El payload push no contiene datos de negocio sensibles. Actúa únicamente como señal de activación ("wake-up") para que la app sincronice datos desde la API.

### Despliegue en Windows Server 2016

- El JSON de cuenta de servicio Firebase **nunca debe estar en el repositorio ni en el ZIP**.
- Ruta recomendada en el servidor: `C:\jacpae\secrets\firebase-service-account.json`
- Permisos: solo lectura para la cuenta de servicio Windows que ejecuta la API.
- Configurar en `.env` del servidor:
  ```
  FIREBASE_CREDENTIALS_PATH=C:\jacpae\secrets\firebase-service-account.json
  FIREBASE_PROJECT_ID=jacpae-prod
  ```
- No requiere cambios en scripts de arranque ni en `make_release_zip.py` (la ruta es externa al proyecto).

### Contadores de push en logs de job

| Contador | Significado |
|---|---|
| `push_sent` | Tokens que han recibido el mensaje correctamente (HTTP 200 de FCM) |
| `push_failed` | Errores transitorios o no reconocidos (red, timeout, error FCM desconocido). No implica desactivación del token. |
| `push_invalidated` | Tokens confirmados inválidos por FCM (`UNREGISTERED`/`INVALID_ARGUMENT`). Desactivados en `push_devices`. |

Un `push_failed > 0` aislado no requiere acción. Un `push_invalidated > 0` es
comportamiento normal (app desinstalada, dispositivo cambiado).

---

## Estructura de almacenamiento en NAS

`PDF_BASE_DIR` define la raíz del almacenamiento de PDFs. En desarrollo apunta a un
directorio local; en producción apunta a la ruta del NAS.

**Facturas:**

```
{PDF_BASE_DIR}/
  {ejercicio}/
    {clt_prov}/
      Factura_{documento}{numero}.pdf
```

Ejemplo: `{PDF_BASE_DIR}/2025/000962/Factura_FA000123.pdf`

**Ofertas:**

```
{PDF_BASE_DIR}/
  offers/
    oferta_YYYYMMDD.pdf
```

La fecha del nombre es la fecha de **expiración** de la oferta. Archivos con nombres
que no coincidan exactamente con el patrón son ignorados.

---

## Variables de entorno

Copiar `.env.example` a `.env` y completar los valores requeridos.

### Obligatorias (sin default; la aplicación no arranca sin ellas)

| Variable | Descripción |
|---|---|
| `SUPABASE_ISS` | Issuer del JWT. Formato: `https://<proyecto>.supabase.co/auth/v1` |
| `SUPABASE_JWKS_URL` | Endpoint JWKS. Formato: `https://<proyecto>.supabase.co/auth/v1/.well-known/jwks.json` |
| `MARIADB_USER` | Usuario de MariaDB |
| `MARIADB_PASSWORD` | Contraseña de MariaDB |
| `MARIADB_DB` | Nombre del schema de ventas (g4) |

### Necesarias para notificaciones y jobs

| Variable | Descripción |
|---|---|
| `SUPABASE_URL` | URL base del proyecto Supabase. Formato: `https://<proyecto>.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key de Supabase. **Solo backend. No exponer en logs ni en cliente.** |

Sin estas dos variables, las consultas a `customer_profiles` y `notifications` no se
ejecutan (el módulo registra un warning y retorna vacío sin lanzar excepción).

### Opcionales con default

| Variable | Default | Descripción |
|---|---|---|
| `APP_ENV` | `development` | En `development` activa endpoints debug y logs adicionales de auth |
| `HOST` | `127.0.0.1` | Dirección de bind de Uvicorn |
| `PORT` | `8000` | Puerto de bind de Uvicorn |
| `SUPABASE_AUD` | `authenticated` | Audience esperado en el JWT |
| `JWKS_CACHE_TTL` | `3600` | Caché de claves JWKS en segundos |
| `JWKS_READY_TIMEOUT` | `2` | Timeout en segundos para el check JWKS en `/health/ready` |
| `PDF_BASE_DIR` | `./_pdfs/invoices_issued` | Ruta raíz de los PDFs |
| `MARIADB_HOST` | `127.0.0.1` | Host de MariaDB |
| `MARIADB_PORT` | `3306` | Puerto de MariaDB |
| `MARIADB_FINAN_DB` | `g4finan` | Schema de contabilidad (mismo host y credenciales que ventas) |
| `GIRO_JOB_ENABLED` | `false` | Activa el job de notificaciones de giros |
| `GIRO_JOB_HOUR` | `8` | Hora de ejecución del job de giros |
| `GIRO_JOB_MINUTE` | `0` | Minuto de ejecución del job de giros |
| `GIRO_DEFAULT_DIAS_AVISO` | `5` | Días de ventana cuando el perfil no especifica `dias_aviso_giro` |
| `REPARTO_JOB_ENABLED` | `false` | Activa el job de notificaciones de reparto |
| `REPARTO_JOB_HOUR` | `8` | Hora de ejecución del job de reparto |
| `REPARTO_JOB_MINUTE` | `0` | Minuto de ejecución del job de reparto |
| `REPARTO_DEFAULT_DIAS_AVISO` | `2` | Días laborables de antelación cuando el perfil no los especifica |
| `OFFER_JOB_ENABLED` | `false` | Activa el job de notificaciones de ofertas |
| `OFFER_JOB_HOUR` | `8` | Hora de ejecución del job de ofertas |
| `OFFER_JOB_MINUTE` | `5` | Minuto de ejecución del job de ofertas |
| `FIREBASE_CREDENTIALS_PATH` | `None` | Ruta absoluta al JSON de cuenta de servicio Firebase. Si no se configura, el push queda desactivado sin error. |
| `FIREBASE_PROJECT_ID` | `None` | ID del proyecto Firebase (p. ej. `jacpae-prod`). Debe coincidir con el JSON de credenciales. |

---

## Seguridad

### Autenticación JWT

Todas las peticiones a endpoints protegidos requieren:

```
Authorization: Bearer <JWT>
```

El token es emitido por Supabase Auth. El backend verifica la firma usando las claves
públicas del endpoint JWKS. Algoritmos aceptados: `RS256`, `ES256`, `ES384`, `ES512`.
Las claves se cachean durante `JWKS_CACHE_TTL` segundos.

- Token expirado: `401 Token expired`
- Firma inválida o `kid` desconocido: `401 Invalid token`
- JWKS no disponible durante verificación: `503 JWKS unavailable`

### Resolución del perfil de cliente

El `clt_prov` (código ERP) nunca se acepta como parámetro del cliente. Se resuelve
siempre desde `customer_profiles` usando el `user_id` del JWT. Si el perfil no existe
o `is_active=false`, el endpoint devuelve `403`.

### RLS en Supabase (tabla `notifications`)

| Operación | Comportamiento |
|---|---|
| SELECT | Solo las notificaciones propias del usuario (`auth.uid() = user_id`) |
| UPDATE | Solo `read_at` de las notificaciones propias |
| INSERT | Sin policy de cliente. Solo el backend puede insertar usando `SERVICE_ROLE_KEY` |
| DELETE | Sin policy — denegado por defecto con RLS activo |

### Credenciales Firebase

El archivo JSON de cuenta de servicio Firebase contiene una clave privada RSA. Nunca
debe incluirse en el repositorio, en el ZIP de distribución ni aparecer en logs. La
ubicación recomendada es fuera del directorio del proyecto (`C:\jacpae\secrets\`), lo
que garantiza que `make_release_zip.py` no lo incluya. La ruta se configura únicamente
en el `.env` del servidor.

### Service Role Key

`SUPABASE_SERVICE_ROLE_KEY` se usa exclusivamente en el backend para leer
`customer_profiles`, insertar notificaciones desde los jobs y leer/actualizar
notificaciones en nombre del usuario. Esta clave no debe aparecer en logs, respuestas
de la API, variables de cliente ni en el repositorio de código.

---

## Migraciones Supabase

Las migraciones se aplican manualmente en el SQL Editor de Supabase, en orden numérico.

| Archivo | Descripción |
|---|---|
| `001_customer_profiles_giro_columns.sql` | Añade `cta_contable`, `avisar_giro` y `dias_aviso_giro` a `customer_profiles` |
| `002_notifications_table.sql` | Crea la tabla `notifications` con índices y RLS. Campo de deduplicación: `source_key` |
| `003_notifications_source_key.sql` | Migración de compatibilidad: renombra `dedup_key` → `source_key` en instalaciones previas. Idempotente. |
| `004_push_devices.sql` | Crea la tabla `push_devices` con `device_token` (UNIQUE), `user_id`, `platform`, `is_active`, timestamps y RLS activo. |

Aplicar siempre en orden. La migración `003` puede re-ejecutarse sin efecto secundario.

---

## Desarrollo local

### Requisitos

- Python 3.12 o superior
- Acceso a MariaDB con los schemas configurados
- Proyecto Supabase con tablas `customer_profiles` y `notifications` creadas

### Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Editar .env con los valores reales
```

### Arranque

```bash
.venv\Scripts\python -m uvicorn app.main:app --app-dir src --host 127.0.0.1 --port 8000
```

### Verificación

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/openapi.json
```

---

## Tests

```bash
.venv\Scripts\python -m pytest tests/ -v
```

Estado actual: todos los tests pasan. Todos los tests usan mocks; no requieren
conexión a MariaDB ni a Supabase.

| Módulo | Cobertura |
|---|---|
| `test_health.py` | Liveness, readiness: DB ok/fail, JWKS ok/fail/skipped |
| `test_invoices.py` | Auth, resolución de perfil, perfil inactivo, errores DB, respuesta 200, codec `invoice_id` |
| `test_invoice_pdf.py` | Auth, validación `invoice_id`, comprobación de ownership, PDF no generado, streaming |
| `test_notifications.py` | Auth, listado, paginación, mark as read, errores 503 |
| `test_offer_pdf.py` | Auth, sin oferta activa, streaming, ausencia de rutas internas en headers |
| `test_offer_service.py` | Selección de oferta más próxima, expiradas, nombres de archivo inválidos |
| `test_offer_job.py` | Construcción de notificación, deduplicación, sin usuarios activos, errores Supabase |
| `test_giro_job.py` | Construcción de notificación, perfiles filtrados, errores DB y Supabase |
| `test_giro_repository.py` | SQL generado, parámetros, pool de contabilidad |
| `test_reparto_job.py` | Cálculo de días laborables, construcción de notificación, deduplicación |
| `test_reparto_repository.py` | SQL generado, parámetros, pool de ventas |
| `test_fcm_service.py` | Configuración degradada, token OAuth2, parsing de errores FCM, envío por token, send_push_to_user completo |

No existe suite de tests para `src/app/api/me.py`.

---

## Limitaciones actuales

- El cálculo de días laborables en el job de reparto excluye únicamente sábados y
  domingos. No incorpora festivos.
- No existe endpoint individual `GET /invoices/{id}` ni `GET /notifications/{id}`.
- El push FCM no incorpora scheduling de reintentos. Un fallo transitorio de red no
  se reintenta; se registra en `push_failed` y el usuario recibe la notificación en
  la próxima ejecución del job.
- Las notificaciones se almacenan en Supabase. El cliente las consulta mediante
  `GET /notifications`.
- No existe panel de administración ni endpoints protegidos por rol admin.
- No existe gestión de tokens de refresco en la API; se delega a Supabase Auth.
- El schema de contabilidad (`MARIADB_FINAN_DB`) comparte host, usuario y contraseña
  con el schema de ventas. No es posible configurar credenciales independientes.

---

## Proceso de empaquetado

El script `tools/make_release_zip.py` genera un ZIP listo para distribuir, sin secretos
ni artefactos de desarrollo.

```bash
.venv\Scripts\python tools\make_release_zip.py --project-root . --out-dir dist --name jacpae_api_update
```

Genera: `dist/jacpae_api_update_YYYYMMDD_HHMMSS.zip`

**Incluye:** `requirements.txt`, `README.md`, `.env.example`, `src/`, `tests/`

**Excluye:** `.env`, `.venv/`, `__pycache__/`, `*.pyc`, `*.log`, certificados y claves

El script valida el ZIP antes de cerrarlo (presencia de `requirements.txt` y `src/app/`).

---

## Despliegue manual en Windows Server

No existen scripts de despliegue en el repositorio.

1. Generar el ZIP con `make_release_zip.py`.
2. Copiar y descomprimir en el servidor (p. ej. `C:\services\jacpae_api\current\`).
3. Mantener el archivo `.env` en una ubicación de configuración fuera del ZIP y sin versionar.
4. Crear el entorno virtual e instalar dependencias:
   ```powershell
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
5. Arrancar con `APP_ENV=production`:
   ```powershell
   .venv\Scripts\python -m uvicorn app.main:app --app-dir src --host 0.0.0.0 --port 8000
   ```
6. Para ejecución continua, registrar como servicio Windows. Este paso no está
   documentado en el repositorio.

---

## Licencia / Autor

No documentado en el repositorio.
