ALTER TABLE merchant ADD (service_area_id VARCHAR2(64))
-- +YOBI STATEMENT
ALTER TABLE menu ADD (category_id VARCHAR2(160))
-- +YOBI STATEMENT
CREATE TABLE service_area (
  service_area_id VARCHAR2(64) PRIMARY KEY,
  city VARCHAR2(120) NOT NULL,
  district VARCHAR2(120) NOT NULL,
  display_name VARCHAR2(120) NOT NULL,
  active NUMBER(1) DEFAULT 1 NOT NULL CHECK (active IN (0, 1))
)
-- +YOBI STATEMENT
CREATE TABLE menu_category (
  category_id VARCHAR2(160) PRIMARY KEY,
  name_ko VARCHAR2(200) NOT NULL,
  name_en VARCHAR2(200) NOT NULL,
  description VARCHAR2(1000) NOT NULL,
  tags_json CLOB NOT NULL CHECK (tags_json IS JSON),
  typical_spice_min NUMBER(1) NOT NULL CHECK (typical_spice_min BETWEEN 0 AND 5),
  typical_spice_max NUMBER(1) NOT NULL CHECK (typical_spice_max BETWEEN 0 AND 5)
)
-- +YOBI STATEMENT
CREATE TABLE ingredient (
  ingredient_id VARCHAR2(160) PRIMARY KEY,
  name_ko VARCHAR2(200) NOT NULL,
  name_en VARCHAR2(200) NOT NULL,
  ingredient_group VARCHAR2(120) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE menu_ingredient (
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  ingredient_id VARCHAR2(160) NOT NULL REFERENCES ingredient(ingredient_id),
  status VARCHAR2(32) NOT NULL,
  source_id VARCHAR2(128),
  is_optional NUMBER(1) DEFAULT 0 NOT NULL CHECK (is_optional IN (0, 1)),
  PRIMARY KEY (menu_id, ingredient_id)
)
-- +YOBI STATEMENT
CREATE TABLE allergen (
  allergen_id VARCHAR2(160) PRIMARY KEY,
  code VARCHAR2(120) UNIQUE NOT NULL,
  name_en VARCHAR2(200) NOT NULL,
  name_ko VARCHAR2(200) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE menu_allergen (
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  allergen_id VARCHAR2(160) NOT NULL REFERENCES allergen(allergen_id),
  status VARCHAR2(32) NOT NULL,
  evidence_id VARCHAR2(64),
  cross_contamination_status VARCHAR2(40) NOT NULL,
  PRIMARY KEY (menu_id, allergen_id)
)
-- +YOBI STATEMENT
CREATE TABLE dietary_attribute (
  attribute_id VARCHAR2(160) PRIMARY KEY,
  code VARCHAR2(120) UNIQUE NOT NULL,
  display_name VARCHAR2(200) NOT NULL
)
-- +YOBI STATEMENT
CREATE TABLE menu_dietary_attribute (
  menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
  attribute_id VARCHAR2(160) NOT NULL REFERENCES dietary_attribute(attribute_id),
  status VARCHAR2(32) NOT NULL,
  evidence_id VARCHAR2(64),
  PRIMARY KEY (menu_id, attribute_id)
)
-- +YOBI STATEMENT
CREATE TABLE option_dietary_conflict (
  option_item_id VARCHAR2(80) NOT NULL REFERENCES menu_option_item(option_item_id),
  rule_code VARCHAR2(120) NOT NULL,
  conflict_status VARCHAR2(64) NOT NULL,
  evidence_id VARCHAR2(64),
  PRIMARY KEY (option_item_id, rule_code)
)
-- +YOBI STATEMENT
CREATE INDEX idx_dietary_menu ON menu_dietary_attribute(menu_id, status)
-- +YOBI STATEMENT
CREATE INDEX idx_allergen_menu ON menu_allergen(menu_id, status)
