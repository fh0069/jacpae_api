-- ============================================================
-- 005: Crear tabla push_devices + RLS
-- Ejecutar en Supabase SQL Editor
-- El backend escribe en esta tabla con SUPABASE_SERVICE_ROLE_KEY.
-- Los clientes autenticados solo pueden consultar sus propios
-- dispositivos. INSERT/UPDATE/DELETE están reservados al backend.
-- ============================================================

-- 1. Crear tabla
CREATE TABLE IF NOT EXISTS public.push_devices (
  id            uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid          NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  device_token  text          NOT NULL UNIQUE,
  platform      text          NOT NULL CHECK (platform IN ('android', 'ios')),
  is_active     boolean       NOT NULL DEFAULT true,
  created_at    timestamptz   NOT NULL DEFAULT now(),
  updated_at    timestamptz   NOT NULL DEFAULT now(),
  last_seen_at  timestamptz
);

-- 2. Índice para queries por usuario
CREATE INDEX IF NOT EXISTS ix_push_devices_user_id
  ON public.push_devices (user_id);

-- ============================================================
-- RLS: Row Level Security
-- ============================================================

-- 3. Activar RLS
ALTER TABLE public.push_devices ENABLE ROW LEVEL SECURITY;

-- 4. SELECT: el usuario solo ve sus propios dispositivos
DO $$
BEGIN
  CREATE POLICY push_devices_select_own
    ON public.push_devices
    FOR SELECT
    USING (auth.uid() = user_id);
EXCEPTION
  WHEN duplicate_object THEN
    RAISE NOTICE 'Policy push_devices_select_own already exists, skipping.';
END;
$$;

-- 5. INSERT: NO hay policy para INSERT desde cliente.
--    Las inserciones las hace el backend con SERVICE_ROLE_KEY,
--    que bypasea RLS.

-- 6. UPDATE: NO hay policy para UPDATE desde cliente.

-- 7. DELETE: NO hay policy para DELETE desde cliente.
--    (Sin policy = denegado por defecto con RLS activo)
