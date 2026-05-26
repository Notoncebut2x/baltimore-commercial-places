-- Example queries against the commercial_places table.
-- Run via: duckdb baltimore_commercial_places.duckdb < sql/example_queries.sql

LOAD spatial;

-- 1. All restaurants with a website
SELECT name, category, website
FROM commercial_places
WHERE category LIKE 'eat_and_drink%'
  AND website IS NOT NULL
ORDER BY name;

-- 2. Top 20 brands by location count
SELECT brand, COUNT(*) AS locations
FROM commercial_places
WHERE brand IS NOT NULL
GROUP BY brand
ORDER BY locations DESC
LIMIT 20;

-- 3. Category breakdown
SELECT category, COUNT(*) AS n
FROM commercial_places
GROUP BY category
ORDER BY n DESC
LIMIT 30;

-- 4. Places missing contact info (data-quality probe)
SELECT COUNT(*) AS no_contact
FROM commercial_places
WHERE phone IS NULL AND email IS NULL AND website IS NULL;

-- 5. Counts by ZIP code
SELECT postcode, COUNT(*) AS n
FROM commercial_places
WHERE postcode IS NOT NULL
GROUP BY postcode
ORDER BY n DESC;
