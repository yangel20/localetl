-- Runs once, on first start of an empty data volume, as POSTGRES_USER.
-- The primary database (POSTGRES_DB, default localetl) is created by the image.
-- Create the throwaway database used by pytest (TEST_DATABASE_URL).
CREATE DATABASE localetl_test;
