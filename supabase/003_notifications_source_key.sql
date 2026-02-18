-- ============================================================
-- 003: Renombrar dedup_key -> source_key en notifications
--
-- Solo es necesaria si la tabla fue creada con 002 antes de
-- esta corrección (campo dedup_key en lugar de source_key).
-- Es idempotente: puede ejecutarse aunque ya esté aplicada.
-- ============================================================

DO $$
DECLARE
  col_dedup   boolean;
  col_source  boolean;
  idx_old     boolean;
BEGIN
  -- Detectar si existe dedup_key
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name   = 'notifications'
      AND column_name  = 'dedup_key'
  ) INTO col_dedup;

  -- Detectar si ya existe source_key
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name   = 'notifications'
      AND column_name  = 'source_key'
  ) INTO col_source;

  IF col_dedup AND NOT col_source THEN
    -- 1. Renombrar columna
    ALTER TABLE public.notifications
      RENAME COLUMN dedup_key TO source_key;
    RAISE NOTICE '003: columna dedup_key renombrada a source_key.';

    -- 2. Renombrar índice antiguo si existe
    SELECT EXISTS (
      SELECT 1 FROM pg_indexes
      WHERE schemaname = 'public'
        AND tablename  = 'notifications'
        AND indexname  = 'uix_notifications_dedup_key'
    ) INTO idx_old;

    IF idx_old THEN
      ALTER INDEX public.uix_notifications_dedup_key
        RENAME TO uix_notifications_source_key;
      RAISE NOTICE '003: índice uix_notifications_dedup_key renombrado a uix_notifications_source_key.';
    END IF;

  ELSIF col_source THEN
    RAISE NOTICE '003: source_key ya existe, nada que hacer.';
  ELSE
    RAISE NOTICE '003: tabla notifications no encontrada o ya tiene source_key.';
  END IF;
END;
$$;

-- 3. Garantizar que el índice único en source_key existe
--    (cubre el caso de instalación fresca con 002 nuevo)
CREATE UNIQUE INDEX IF NOT EXISTS uix_notifications_source_key
  ON public.notifications (source_key);
