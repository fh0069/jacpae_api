-- ============================================================
-- CHECKPOINT 1a: Añadir columnas de aviso de giro a customer_profiles
-- Ejecutar en Supabase SQL Editor
-- ============================================================

-- 1. Añadir columnas (IF NOT EXISTS evita error si ya existen)
ALTER TABLE public.customer_profiles
  ADD COLUMN IF NOT EXISTS cta_contable text,
  ADD COLUMN IF NOT EXISTS avisar_giro boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS dias_aviso_giro integer NOT NULL DEFAULT 5;

-- 2. CHECK constraint con bloque DO para ignorar si ya existe
--    (Supabase/PostgreSQL no soporta ADD CONSTRAINT IF NOT EXISTS)
DO $$
BEGIN
  ALTER TABLE public.customer_profiles
    ADD CONSTRAINT chk_dias_aviso_giro_non_negative
    CHECK (dias_aviso_giro >= 0);
EXCEPTION
  WHEN duplicate_object THEN
    RAISE NOTICE 'Constraint chk_dias_aviso_giro_non_negative already exists, skipping.';
END;
$$;
