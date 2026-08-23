BEGIN
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE merchant MODIFY (name_en NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE merchant MODIFY (description NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE merchant MODIFY (flavor_profile NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE merchant MODIFY (packaging_signal NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
END;
-- +YOBI STATEMENT
BEGIN
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu MODIFY (name_en NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu MODIFY (description NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu MODIFY (cultural_description NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu MODIFY (serves_min NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu MODIFY (serves_max NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu MODIFY (spice_level NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
END;
-- +YOBI STATEMENT
BEGIN
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu_option_group MODIFY (name_en NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_group MODIFY (name_ko VARCHAR2(500 CHAR))';
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu_option_group MODIFY (description NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
END;
-- +YOBI STATEMENT
BEGIN
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu_option_item MODIFY (name_en NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_item MODIFY (name_ko VARCHAR2(500 CHAR))';
  BEGIN
    EXECUTE IMMEDIATE 'ALTER TABLE menu_option_item MODIFY (description NULL)';
  EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1451 THEN RAISE; END IF;
  END;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE merchant ADD (catalog_import_id VARCHAR2(64))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE merchant ADD (data_origin VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE merchant ADD (source_platform VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE merchant ADD (source_merchant_id VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE merchant ADD (source_collected_at TIMESTAMP WITH TIME ZONE)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (catalog_import_id VARCHAR2(64))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (data_origin VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (source_platform VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (source_menu_id VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (source_section_id VARCHAR2(160))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (name_en_status VARCHAR2(32))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (cultural_description_status VARCHAR2(32))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (serves_status VARCHAR2(32))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (spice_status VARCHAR2(32))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu ADD (dietary_data_status VARCHAR2(32))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_group ADD (catalog_import_id VARCHAR2(64))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_group ADD (source_option_group_id VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_group ADD (normalization_code VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_item ADD (catalog_import_id VARCHAR2(64))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE menu_option_item ADD (source_option_item_key VARCHAR2(80))';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -1430 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE catalog_import_batch (
      catalog_import_id VARCHAR2(64) PRIMARY KEY,
      catalog_release_id VARCHAR2(160) UNIQUE NOT NULL,
      data_origin VARCHAR2(80) NOT NULL,
      source_platform VARCHAR2(80) NOT NULL,
      source_zip_sha256 VARCHAR2(64) NOT NULL,
      source_xlsx_sha256 VARCHAR2(64) NOT NULL,
      source_summary_sha256 VARCHAR2(64) NOT NULL,
      package_sha256 VARCHAR2(64) NOT NULL,
      selection_manifest_sha256 VARCHAR2(64) NOT NULL,
      selection_algorithm_version VARCHAR2(160) NOT NULL,
      collection_location VARCHAR2(1000) NOT NULL,
      source_collected_at TIMESTAMP WITH TIME ZONE NOT NULL,
      selected_merchant_count NUMBER(10) NOT NULL,
      expected_counts_json CLOB NOT NULL CHECK (expected_counts_json IS JSON),
      actual_counts_json CLOB NOT NULL CHECK (actual_counts_json IS JSON),
      diagnostics_json CLOB NOT NULL CHECK (diagnostics_json IS JSON),
      status VARCHAR2(16) NOT NULL CHECK (status IN ('LOADING','ACTIVE','FAILED','RETIRED')),
      started_at TIMESTAMP WITH TIME ZONE NOT NULL,
      completed_at TIMESTAMP WITH TIME ZONE
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE merchant_source_detail (
      merchant_id VARCHAR2(32) PRIMARY KEY REFERENCES merchant(merchant_id),
      catalog_import_id VARCHAR2(64) NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
      latitude VARCHAR2(80),
      longitude VARCHAR2(80),
      distance_m BINARY_DOUBLE,
      vertical_type VARCHAR2(80),
      vertical_sub_type VARCHAR2(80),
      current_open_status VARCHAR2(80),
      review_average BINARY_DOUBLE,
      review_count NUMBER(12),
      review_image_count NUMBER(12),
      review_reply_count NUMBER(12),
      franchise_json CLOB CHECK (franchise_json IS JSON),
      vendor_categories_json CLOB NOT NULL CHECK (vendor_categories_json IS JSON),
      tags_json CLOB NOT NULL CHECK (tags_json IS JSON),
      image_json CLOB NOT NULL CHECK (image_json IS JSON),
      serving_type_json CLOB NOT NULL CHECK (serving_type_json IS JSON),
      representative_menus_json CLOB NOT NULL CHECK (representative_menus_json IS JSON),
      operational_json CLOB NOT NULL CHECK (operational_json IS JSON)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_source_detail (
      menu_id VARCHAR2(32) PRIMARY KEY REFERENCES menu(menu_id),
      catalog_import_id VARCHAR2(64) NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
      source_section_id VARCHAR2(160),
      review_count NUMBER(12),
      liquor NUMBER(1) NOT NULL CHECK (liquor IN (0,1)),
      is_adult NUMBER(1) NOT NULL CHECK (is_adult IN (0,1)),
      verified_adult NUMBER(1) NOT NULL CHECK (verified_adult IN (0,1)),
      soldout NUMBER(1) NOT NULL CHECK (soldout IN (0,1)),
      stock_amount NUMBER(12),
      thumbnail_json CLOB NOT NULL CHECK (thumbnail_json IS JSON),
      badges_json CLOB NOT NULL CHECK (badges_json IS JSON),
      announcement_json CLOB CHECK (announcement_json IS JSON),
      price_json CLOB NOT NULL CHECK (price_json IS JSON),
      point NUMBER(12),
      point_promotions_json CLOB NOT NULL CHECK (point_promotions_json IS JSON),
      operational_json CLOB NOT NULL CHECK (operational_json IS JSON)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_source_section (
      source_section_key VARCHAR2(220) PRIMARY KEY,
      catalog_import_id VARCHAR2(64) NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
      merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
      source_section_id VARCHAR2(160) NOT NULL,
      section_type VARCHAR2(80),
      title VARCHAR2(500),
      description VARCHAR2(2000),
      liquor NUMBER(1) NOT NULL CHECK (liquor IN (0,1)),
      is_adult NUMBER(1) NOT NULL CHECK (is_adult IN (0,1)),
      disposable NUMBER(1) NOT NULL CHECK (disposable IN (0,1)),
      additional_discounted NUMBER(1) NOT NULL CHECK (additional_discounted IN (0,1)),
      sort_order NUMBER(6) NOT NULL
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE menu_source_section_item (
      source_section_key VARCHAR2(220) NOT NULL REFERENCES menu_source_section(source_section_key),
      menu_id VARCHAR2(32) NOT NULL REFERENCES menu(menu_id),
      sort_order NUMBER(6) NOT NULL,
      PRIMARY KEY (source_section_key, menu_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE source_option (
      source_option_key VARCHAR2(80) PRIMARY KEY,
      catalog_import_id VARCHAR2(64) NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
      merchant_id VARCHAR2(32) NOT NULL REFERENCES merchant(merchant_id),
      source_option_id VARCHAR2(80) NOT NULL,
      name_ko VARCHAR2(300) NOT NULL,
      description VARCHAR2(1000),
      origin_price NUMBER(12),
      final_price NUMBER(12),
      discount_percent BINARY_DOUBLE,
      soldout NUMBER(1) NOT NULL CHECK (soldout IN (0,1)),
      stock_amount NUMBER(12),
      deposit_json CLOB NOT NULL CHECK (deposit_json IS JSON),
      reusable_packaging NUMBER(1) NOT NULL CHECK (reusable_packaging IN (0,1)),
      source_json CLOB NOT NULL CHECK (source_json IS JSON),
      CONSTRAINT uq_source_option_id UNIQUE (catalog_import_id, merchant_id, source_option_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE option_group_source_detail (
      option_group_id VARCHAR2(64) PRIMARY KEY REFERENCES menu_option_group(option_group_id),
      catalog_import_id VARCHAR2(64) NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
      source_option_group_id VARCHAR2(80) NOT NULL,
      multiple_limit NUMBER(6),
      available_quantity NUMBER(1) NOT NULL CHECK (available_quantity IN (0,1)),
      available_multiple NUMBER(1) NOT NULL CHECK (available_multiple IN (0,1)),
      original_min_select NUMBER(6) NOT NULL,
      original_max_select NUMBER(6) NOT NULL,
      badges_json CLOB NOT NULL CHECK (badges_json IS JSON),
      tooltip_message VARCHAR2(2000),
      source_json CLOB NOT NULL CHECK (source_json IS JSON)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE q'^
    CREATE TABLE catalog_source_payload (
      payload_id VARCHAR2(80) PRIMARY KEY,
      catalog_import_id VARCHAR2(64) NOT NULL REFERENCES catalog_import_batch(catalog_import_id),
      entity_type VARCHAR2(32) NOT NULL CHECK (entity_type IN ('SHOP','MENU_RESPONSE')),
      source_entity_id VARCHAR2(80) NOT NULL,
      payload_sha256 VARCHAR2(64) NOT NULL,
      raw_payload CLOB NOT NULL CHECK (raw_payload IS JSON),
      CONSTRAINT uq_catalog_payload UNIQUE (catalog_import_id, entity_type, source_entity_id)
    )
  ^';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_catalog_batch_status ON catalog_import_batch(status, completed_at)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_merchant_catalog_import ON merchant(catalog_import_id, data_origin)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_menu_catalog_import ON menu(catalog_import_id, merchant_id, availability)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_source_section_merchant ON menu_source_section(merchant_id, sort_order)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_option_group_menu ON menu_option_group(menu_id, sort_order)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_option_item_group ON menu_option_item(option_group_id, availability, sort_order)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
-- +YOBI STATEMENT
BEGIN
  EXECUTE IMMEDIATE 'CREATE INDEX idx_source_option_merchant ON source_option(merchant_id, source_option_id)';
EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF;
END;
