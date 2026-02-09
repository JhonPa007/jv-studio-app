-- Run this SQL command in your database tool (pgAdmin, DBeaver) or terminal using psql
-- This adds the missing 'saldo_monedero' column to the 'clientes' table.

DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='clientes' AND column_name='saldo_monedero') THEN 
        ALTER TABLE clientes ADD COLUMN saldo_monedero DECIMAL(12, 2) DEFAULT 0.00; 
    END IF; 
END $$;
