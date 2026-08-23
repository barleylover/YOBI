from __future__ import annotations

from hashlib import sha256
from typing import Literal, cast

LanguageCode = Literal["ko", "en", "ja"]


# Release-seeded product examples. They are reference dishes for the control,
# not claims that every person from a country has the same spice tolerance.
COUNTRY_SPICE_EXAMPLES: dict[str, dict[LanguageCode, str]] = {
    "US": {"ko": "버팔로 윙", "en": "Buffalo wings", "ja": "バッファローウィング"},
    "GB": {"ko": "치킨 티카 마살라", "en": "Chicken tikka masala", "ja": "チキンティッカマサラ"},
    "CA": {"ko": "매콤한 치킨 윙", "en": "Spicy chicken wings", "ja": "スパイシーチキンウィング"},
    "AU": {"ko": "페리페리 치킨", "en": "Peri-peri chicken", "ja": "ペリペリチキン"},
    "NZ": {"ko": "스위트 칠리 치킨", "en": "Sweet chilli chicken", "ja": "スイートチリチキン"},
    "IE": {"ko": "스파이스드 치킨", "en": "Spiced chicken", "ja": "スパイスチキン"},
    "KR": {"ko": "신라면", "en": "Shin Ramyun", "ja": "辛ラーメン"},
    "JP": {"ko": "중간 매운 카레", "en": "Medium-spicy Japanese curry", "ja": "中辛カレー"},
    "CN": {"ko": "마파두부", "en": "Mapo tofu", "ja": "麻婆豆腐"},
    "TW": {"ko": "매운 우육면", "en": "Spicy beef noodle soup", "ja": "辛い牛肉麺"},
    "HK": {"ko": "칠리 오일 완탕", "en": "Wontons with chilli oil", "ja": "ラー油ワンタン"},
    "SG": {"ko": "락사", "en": "Laksa", "ja": "ラクサ"},
    "ES": {"ko": "파타타스 브라바스", "en": "Patatas bravas", "ja": "パタタス・ブラバス"},
    "MX": {"ko": "살사 로하 타코", "en": "Tacos with salsa roja", "ja": "サルサロハのタコス"},
    "AR": {"ko": "치미추리 초리소", "en": "Chorizo with chimichurri", "ja": "チミチュリのチョリソ"},
    "CO": {"ko": "아히 소스 엠파나다", "en": "Empanadas with ají sauce", "ja": "アヒソースのエンパナーダ"},
    "FR": {"ko": "매콤한 머스터드 치킨", "en": "Chicken with spicy mustard", "ja": "辛口マスタードチキン"},
    "BE": {"ko": "사무라이 소스 프리츠", "en": "Fries with samurai sauce", "ja": "サムライソースのフリッツ"},
    "DE": {"ko": "커리부어스트", "en": "Currywurst", "ja": "カリーヴルスト"},
    "AT": {"ko": "매콤한 굴라시", "en": "Spiced goulash", "ja": "スパイス入りグーラシュ"},
    "CH": {"ko": "칠리 라클렛", "en": "Raclette with chilli", "ja": "チリ入りラクレット"},
    "IT": {"ko": "아라비아타 파스타", "en": "Pasta all'arrabbiata", "ja": "アラビアータ"},
    "PT": {"ko": "피리피리 치킨", "en": "Piri-piri chicken", "ja": "ピリピリチキン"},
    "BR": {"ko": "말라게타 소스 치킨", "en": "Chicken with malagueta sauce", "ja": "マラゲータソースのチキン"},
    "TH": {"ko": "팟 끄라파오", "en": "Pad kra pao", "ja": "ガパオライス"},
    "VN": {"ko": "매운 분보후에", "en": "Spicy bún bò Huế", "ja": "辛いブンボーフエ"},
    "ID": {"ko": "삼발 고렝", "en": "Sambal goreng", "ja": "サンバルゴレン"},
    "MY": {"ko": "커리 락사", "en": "Curry laksa", "ja": "カレーラクサ"},
    "SA": {"ko": "샤타 소스 샤와르마", "en": "Shawarma with shatta", "ja": "シャッタソースのシャワルマ"},
    "AE": {"ko": "매콤한 샤와르마", "en": "Spicy shawarma", "ja": "スパイシーシャワルマ"},
    "EG": {"ko": "샤타 소스 코샤리", "en": "Koshari with shatta", "ja": "シャッタ入りコシャリ"},
    "IN": {"ko": "치킨 빈달루", "en": "Chicken vindaloo", "ja": "チキンビンダルー"},
    "RU": {"ko": "아지카 소스 치킨", "en": "Chicken with adjika", "ja": "アジカソースのチキン"},
    "PH": {"ko": "비콜 익스프레스", "en": "Bicol Express", "ja": "ビコール・エクスプレス"},
    "TR": {"ko": "아다나 케밥", "en": "Adana kebab", "ja": "アダナケバブ"},
    "NL": {"ko": "사테 소스 프리츠", "en": "Fries with satay sauce", "ja": "サテソースのフライドポテト"},
}


def effective_language(locale: str) -> LanguageCode:
    language = locale.strip().lower().split("-", 1)[0].split("_", 1)[0]
    return cast(LanguageCode, language if language in {"ko", "ja"} else "en")


def representative_dish(country_code: str, locale: str) -> str:
    language = effective_language(locale)
    values = COUNTRY_SPICE_EXAMPLES.get(country_code.upper())
    if values is not None:
        return values[language]
    return {"ko": "중간 매운 음식", "ja": "中辛の料理", "en": "a medium-spicy dish"}[
        language
    ]


_SPICE_SCALE_ANCHORS: dict[str, dict[LanguageCode, tuple[dict[str, object], ...]]] = {
    "US": {
        "en": (
            {"level": 2, "familiar_dish": "Mild Buffalo wings", "korean_dish": "Mild kimchi fried rice", "approximate_shu": 500},
            {"level": 4, "familiar_dish": "Hot Buffalo wings", "korean_dish": "Tteokbokki", "approximate_shu": 5_000},
        ),
        "ko": (
            {"level": 2, "familiar_dish": "순한 버팔로 윙", "korean_dish": "순한 김치볶음밥", "approximate_shu": 500},
            {"level": 4, "familiar_dish": "매운 버팔로 윙", "korean_dish": "떡볶이", "approximate_shu": 5_000},
        ),
        "ja": (
            {"level": 2, "familiar_dish": "マイルドなバッファローウィング", "korean_dish": "マイルドなキムチチャーハン", "approximate_shu": 500},
            {"level": 4, "familiar_dish": "辛口バッファローウィング", "korean_dish": "トッポッキ", "approximate_shu": 5_000},
        ),
    },
    "JP": {
        "en": (
            {"level": 2, "familiar_dish": "Medium-spicy Japanese curry", "korean_dish": "Mild kimchi fried rice", "approximate_shu": 500},
            {"level": 4, "familiar_dish": "Extra-hot Japanese curry", "korean_dish": "Tteokbokki", "approximate_shu": 5_000},
        ),
        "ko": (
            {"level": 2, "familiar_dish": "중간 매운 일본 카레", "korean_dish": "순한 김치볶음밥", "approximate_shu": 500},
            {"level": 4, "familiar_dish": "아주 매운 일본 카레", "korean_dish": "떡볶이", "approximate_shu": 5_000},
        ),
        "ja": (
            {"level": 2, "familiar_dish": "中辛カレー", "korean_dish": "マイルドなキムチチャーハン", "approximate_shu": 500},
            {"level": 4, "familiar_dish": "激辛カレー", "korean_dish": "トッポッキ", "approximate_shu": 5_000},
        ),
    },
}


def spice_scale_anchors(country_code: str, locale: str) -> list[dict[str, object]]:
    """Return optional, explicitly approximate demo anchors for the UI control."""

    anchors = _SPICE_SCALE_ANCHORS.get(country_code.upper(), {}).get(effective_language(locale), ())
    return [dict(anchor) for anchor in anchors]


def example_seed_hash(seed: str, country_code: str, language_code: LanguageCode) -> str:
    value = f"{seed}|country-spice-example-v1|{country_code}|{language_code}"
    return sha256(value.encode("utf-8")).hexdigest()
