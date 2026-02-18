-- ============================================================
-- 002: Crear tabla notifications + RLS
-- Ejecutar en Supabase SQL Editor
-- NOTA: el campo de deduplicación se llama source_key.
--       Si partiste de una instalación previa con dedup_key,
--       aplica primero 003_notifications_source_key.sql.
-- ============================================================

-- 1. Crear tabla
CREATE TABLE IF NOT EXISTS public.notifications (
  id          uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid          NOT NULL,
  type        text          NOT NULL,
  title       text          NOT NULL,
  body        text,
  data        jsonb         NOT NULL DEFAULT '{}'::jsonb,
  source_key  text          NOT NULL,
  created_at  timestamptz   NOT NULL DEFAULT now(),
  read_at     timestamptz
);

-- 2. Índice único en source_key (deduplicación)
CREATE UNIQUE INDEX IF NOT EXISTS uix_notifications_source_key
  ON public.notifications (source_key);

-- 3. Índice para queries por usuario + orden cronológico
CREATE INDEX IF NOT EXISTS ix_notifications_user_created
  ON public.notifications (user_id, created_at DESC);

-- ============================================================
-- RLS: Row Level Security
-- ============================================================

-- 4. Activar RLS
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

-- 5. SELECT: el usuario solo ve sus propias notificaciones
DO $$
BEGIN
  CREATE POLICY notifications_select_own
    ON public.notifications
    FOR SELECT
    USING (auth.uid() = user_id);
EXCEPTION
  WHEN duplicate_object THEN
    RAISE NOTICE 'Policy notifications_select_own already exists, skipping.';
END;
$$;

-- 6. UPDATE: el usuario solo puede actualizar read_at de sus notificaciones
--    (WITH CHECK garantiza que no cambie el user_id)
DO $$
BEGIN
  CREATE POLICY notifications_update_read
    ON public.notifications
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
EXCEPTION
  WHEN duplicate_object THEN
    RAISE NOTICE 'Policy notifications_update_read already exists, skipping.';
END;
$$;

-- 7. INSERT: NO hay policy para INSERT desde cliente.
--    Las inserciones las hace el backend con SERVICE_ROLE_KEY,
--    que bypasea RLS. Así ningún cliente puede crear notificaciones
--    falsas directamente vía PostgREST.

-- 8. DELETE: No se permite borrar notificaciones desde cliente.
--    (Sin policy = denegado por defecto con RLS activo)
