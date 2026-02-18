-- ============================================================
-- 004: Añadir event_date a notifications y columnas de reparto
--      a customer_profiles
--
-- Corrige dos incoherencias entre el backend Python y el esquema:
--   1. notifications: faltaba la columna event_date, que el backend
--      envía en cada INSERT de notificación.
--   2. customer_profiles: faltaban avisar_reparto y dias_aviso_reparto,
--      usadas por reparto_job para filtrar perfiles y calcular el
--      número de días laborables de antelación.
--
-- Idempotente: puede ejecutarse múltiples veces sin error ni pérdida
-- de datos. No modifica ni elimina ninguna columna, índice ni tabla
-- existente.
-- ============================================================


-- ============================================================
-- SECCIÓN 1: notifications — añadir columna event_date
-- ============================================================

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name   = 'notifications'
      AND column_name  = 'event_date'
  ) THEN
    ALTER TABLE public.notifications
      ADD COLUMN event_date date NOT NULL DEFAULT CURRENT_DATE;
    RAISE NOTICE '004: columna event_date añadida a notifications.';
  ELSE
    RAISE NOTICE '004: event_date ya existe en notifications, nada que hacer.';
  END IF;
END;
$$;


-- ============================================================
-- SECCIÓN 2: customer_profiles — añadir columnas de reparto
-- ============================================================

-- Añadir columnas (IF NOT EXISTS evita error si ya existen)
ALTER TABLE public.customer_profiles
  ADD COLUMN IF NOT EXISTS avisar_reparto    boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS dias_aviso_reparto integer NOT NULL DEFAULT 2;

-- CHECK constraint: dias_aviso_reparto debe estar entre 1 y 30
-- (Supabase/PostgreSQL no soporta ADD CONSTRAINT IF NOT EXISTS)
DO $$
BEGIN
  ALTER TABLE public.customer_profiles
    ADD CONSTRAINT chk_dias_aviso_reparto_range
    CHECK (dias_aviso_reparto BETWEEN 1 AND 30);
  RAISE NOTICE '004: constraint chk_dias_aviso_reparto_range añadida.';
EXCEPTION
  WHEN duplicate_object THEN
    RAISE NOTICE '004: constraint chk_dias_aviso_reparto_range ya existe, saltando.';
END;
$$;
