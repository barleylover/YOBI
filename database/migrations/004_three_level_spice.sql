UPDATE user_profile
SET spice_tolerance = CASE
  WHEN spice_tolerance <= 1 THEN 1
  WHEN spice_tolerance <= 3 THEN 2
  ELSE 3
END
-- +YOBI STATEMENT
UPDATE menu
SET spice_level = CASE
  WHEN spice_level <= 1 THEN 1
  WHEN spice_level <= 3 THEN 2
  ELSE 3
END
-- +YOBI STATEMENT
UPDATE menu_category
SET typical_spice_min = CASE
      WHEN typical_spice_min <= 1 THEN 1
      WHEN typical_spice_min <= 3 THEN 2
      ELSE 3
    END,
    typical_spice_max = CASE
      WHEN typical_spice_max <= 1 THEN 1
      WHEN typical_spice_max <= 3 THEN 2
      ELSE 3
    END
-- +YOBI STATEMENT
BEGIN
  FOR item IN (
    SELECT table_name, constraint_name
    FROM user_constraints
    WHERE constraint_type = 'C'
      AND table_name IN ('USER_PROFILE', 'MENU', 'MENU_CATEGORY')
      AND (
        UPPER(search_condition_vc) LIKE '%SPICE_TOLERANCE%'
        OR UPPER(search_condition_vc) LIKE '%SPICE_LEVEL%'
        OR UPPER(search_condition_vc) LIKE '%TYPICAL_SPICE_MIN%'
        OR UPPER(search_condition_vc) LIKE '%TYPICAL_SPICE_MAX%'
      )
  ) LOOP
    EXECUTE IMMEDIATE 'ALTER TABLE ' || item.table_name || ' DROP CONSTRAINT ' || item.constraint_name;
  END LOOP;
END;
-- +YOBI STATEMENT
ALTER TABLE user_profile ADD CONSTRAINT chk_profile_spice_3 CHECK (spice_tolerance BETWEEN 1 AND 3)
-- +YOBI STATEMENT
ALTER TABLE menu ADD CONSTRAINT chk_menu_spice_3 CHECK (spice_level BETWEEN 1 AND 3)
-- +YOBI STATEMENT
ALTER TABLE menu_category ADD CONSTRAINT chk_category_spice_min_3 CHECK (typical_spice_min BETWEEN 1 AND 3)
-- +YOBI STATEMENT
ALTER TABLE menu_category ADD CONSTRAINT chk_category_spice_max_3 CHECK (typical_spice_max BETWEEN 1 AND 3)
