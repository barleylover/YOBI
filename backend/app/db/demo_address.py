from __future__ import annotations

import json
from typing import Any, Final

DEMO_ADDRESS_PLACE_ID: Final = "hotel_demo_01"
DEMO_ADDRESS_SERVICE_AREA_ID: Final = "area_myeongdong"
DEMO_ADDRESS_NAME_EN: Final = "YOBI Myeongdong Hotel"
DEMO_ADDRESS_NAME_KO: Final = "요비 명동 호텔"
DEMO_ADDRESS_ROAD: Final = "서울특별시 중구 데모로 21"
DEMO_ADDRESS_POSTAL_CODE: Final = "04501"
DEMO_ADDRESS_CITY: Final = "Seoul"
DEMO_ADDRESS_FIXTURE_SHA256: Final = (
    "49f7f262d369a904b3b4ae395ec438bb5fcd98581b643dcfa32bbf4bbec08876"
)


def demo_address_row() -> dict[str, Any]:
    return {
        "place_id": DEMO_ADDRESS_PLACE_ID,
        "name_ko": DEMO_ADDRESS_NAME_KO,
        "name_en": DEMO_ADDRESS_NAME_EN,
        "aliases_json": json.dumps(
            ["YOBI Hotel Myeongdong", "요비호텔"],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "road_address": DEMO_ADDRESS_ROAD,
        "postal_code": DEMO_ADDRESS_POSTAL_CODE,
        "city": DEMO_ADDRESS_CITY,
        "delivery_hint": "Please leave the order with the hotel front desk.",
        "fixture_sha256": DEMO_ADDRESS_FIXTURE_SHA256,
        "service_area_id": DEMO_ADDRESS_SERVICE_AREA_ID,
        "is_synthetic": 1,
    }


def upsert_demo_address(cursor: Any, *, oracle: bool) -> None:
    row = demo_address_row()
    if oracle:
        cursor.execute(
            """
            MERGE INTO address_place target
            USING (SELECT :place_id AS place_id FROM dual) source
            ON (target.place_id=source.place_id)
            WHEN MATCHED THEN UPDATE SET
              target.name_ko=:name_ko,
              target.name_en=:name_en,
              target.aliases_json=:aliases_json,
              target.road_address=:road_address,
              target.postal_code=:postal_code,
              target.city=:city,
              target.delivery_hint=:delivery_hint,
              target.fixture_sha256=:fixture_sha256,
              target.service_area_id=:service_area_id,
              target.is_synthetic=:is_synthetic
            WHEN NOT MATCHED THEN INSERT (
              place_id,name_ko,name_en,aliases_json,road_address,postal_code,
              city,delivery_hint,fixture_sha256,service_area_id,is_synthetic
            ) VALUES (
              :place_id,:name_ko,:name_en,:aliases_json,:road_address,:postal_code,
              :city,:delivery_hint,:fixture_sha256,:service_area_id,:is_synthetic
            )
            """,
            row,
        )
    else:
        cursor.execute(
            """
            INSERT INTO address_place(
              place_id,name_ko,name_en,aliases_json,road_address,postal_code,
              city,delivery_hint,fixture_sha256,service_area_id,is_synthetic
            ) VALUES (
              :place_id,:name_ko,:name_en,:aliases_json,:road_address,:postal_code,
              :city,:delivery_hint,:fixture_sha256,:service_area_id,:is_synthetic
            )
            ON CONFLICT(place_id) DO UPDATE SET
              name_ko=excluded.name_ko,
              name_en=excluded.name_en,
              aliases_json=excluded.aliases_json,
              road_address=excluded.road_address,
              postal_code=excluded.postal_code,
              city=excluded.city,
              delivery_hint=excluded.delivery_hint,
              fixture_sha256=excluded.fixture_sha256,
              service_area_id=excluded.service_area_id,
              is_synthetic=excluded.is_synthetic
            """,
            row,
        )


def demo_address_status(cursor: Any) -> dict[str, int | bool]:
    row = demo_address_row()
    parameters = {
        key: row[key]
        for key in (
            "place_id",
            "name_ko",
            "name_en",
            "road_address",
            "postal_code",
            "city",
            "fixture_sha256",
            "service_area_id",
            "is_synthetic",
        )
    }
    cursor.execute("SELECT COUNT(*) FROM address_place")
    total = int(cursor.fetchone()[0])
    cursor.execute(
        """
        SELECT COUNT(*) FROM address_place place
        JOIN service_area area ON area.service_area_id=place.service_area_id
        WHERE place.place_id=:place_id
          AND place.name_ko=:name_ko
          AND place.name_en=:name_en
          AND place.road_address=:road_address
          AND place.postal_code=:postal_code
          AND place.city=:city
          AND place.fixture_sha256=:fixture_sha256
          AND place.service_area_id=:service_area_id
          AND place.is_synthetic=:is_synthetic
          AND area.active=1
        """,
        parameters,
    )
    matching = int(cursor.fetchone()[0])
    return {"total": total, "matching": matching, "ready": total == matching == 1}
