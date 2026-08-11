from __future__ import annotations

import hashlib
import json
import logging
from _thread import LockType
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from app.core.config import Settings
from app.core.logging import log_event
from app.db.repository import YobiRepository
from app.db.seed_data import CATEGORIES
from app.domain.dialogue import (
    DialogueAct,
    FallbackReason,
    MealNeedState,
    ReadinessDecision,
    RecommendationCandidate,
    RecommendationResult,
    RecommendationSnapshot,
)
from app.domain.knowledge import GroundedMenuKnowledge
from app.domain.models import AssistantTurn, Card, CartItemInput, ChatState, Profile, Session
from app.genai.agent_loop import AgentLoop
from app.genai.contracts import GenAIProviderError
from app.genai.grounding import GroundedResponseValidator
from app.genai.tool_registry import ToolRegistry
from app.rag.embeddings import routed_knowledge_facets
from app.services.demo_control import DemoControl
from app.services.dialogue_engine import DialogueEngine

_SERVER_NARRATIVE_LANGUAGES = {"English", "한국어", "日本語", "Español"}
_CHAT_LANGUAGE_ALIASES = {
    "english": "English",
    "korean": "한국어",
    "한국어": "한국어",
    "japanese": "日本語",
    "日本語": "日本語",
    "spanish": "Español",
    "español": "Español",
}

_NEEDS_COPY = {
    "English": {
        "greet": (
            "Hi! I’ll get to know what sounds good before showing menus. Would you like "
            "something warm and comforting, light and fresh, or another direction?"
        ),
        "held": (
            "Of course—I’ll hold the menu recommendations and ask one thing at a time. "
            "What kind of taste or feeling would suit this meal?"
        ),
        "meal_direction": (
            "No problem—we do not need to choose yet. Would you prefer something warm, "
            "something crisp, or a light meal?"
        ),
        "taste_or_texture": (
            "That helps. Which matters more today: a savory or sweet taste, or a chewy, "
            "crispy, or soft texture?"
        ),
        "budget": "What budget would you like me to keep the meal under?",
        "party_size": "Will this be just for you, or are you sharing?",
        "ready_confirmation": ("I have enough context. Would you like me to recommend menus now?"),
        "greet_replies": [
            "Warm and comforting",
            "Light and fresh",
            "I don't know yet",
        ],
        "held_replies": ["Warm and savory", "Crispy and filling", "Light and mild"],
    },
    "한국어": {
        "greet": (
            "안녕하세요! 바로 메뉴를 보여드리기 전에 취향을 먼저 알아볼게요. "
            "따뜻하고 든든한 음식과 가볍고 산뜻한 음식 중 어느 쪽이 끌리세요?"
        ),
        "held": (
            "알겠어요. 메뉴 추천은 잠시 보류하고 한 번에 하나씩 여쬈볼게요. "
            "오늘은 어떤 맛이나 느낌의 음식이 좋으세요?"
        ),
        "meal_direction": (
            "아직 고르지 않아도 괜찮아요. 따뜻한 음식, 바삭한 음식, "
            "가벼운 한 끼 중 어느 쪽이 좋으세요?"
        ),
        "taste_or_texture": (
            "좋아요. 오늘은 짭짤한 맛과 달콤한 맛 중 무엇이, 또 쫄깃하거나 "
            "바삭하거나 부드러운 식감 중 무엇이 더 중요한가요?"
        ),
        "budget": "예산은 얼마 이하로 맞추면 될까요?",
        "party_size": "혼자 드시나요, 아니면 몇 명이 함께 드시나요?",
        "ready_confirmation": "필요한 맥락을 충분히 알았어요. 이제 메뉴를 추천할까요?",
        "greet_replies": ["따뜻하고 든든한 음식", "가볍고 산뜻한 음식", "아직 모르겠어요"],
        "held_replies": ["따뜻하고 짭짤한 맛", "바삭하고 든든한 음식", "가볍고 순한 맛"],
    },
    "日本語": {
        "greet": (
            "こんにちは。メニューを表示する前に、今食べたい感じを教えてください。"
            "温かくてほっとするもの、軽くてさっぱりしたもの、それとも別の方向がよいですか？"
        ),
        "held": (
            "わかりました。おすすめは一旦保留にし、一つずつお聞きします。"
            "今日はどんな味や食べ心地がよいですか？"
        ),
        "meal_direction": (
            "まだ選ばなくても大丈夫です。温かいもの、カリッとしたもの、軽い食事のどれがよいですか？"
        ),
        "taste_or_texture": (
            "今日は、うま味と甘味のどちら、またはもちもち・カリカリ・"
            "やわらかい食感のどれが大切ですか？"
        ),
        "budget": "予算の上限はいくらですか？",
        "party_size": "お一人ですか、それとも何人かでシェアしますか？",
        "ready_confirmation": "必要な条件が揃いました。メニューをおすすめしましょうか？",
        "greet_replies": [
            "温かくてほっとする (warm and comforting)",
            "軽くてさっぱり (light and fresh)",
            "まだわからない (I don't know yet)",
        ],
        "held_replies": [
            "温かくてうま味 (warm and savory)",
            "カリッとして満足感 (crispy and filling)",
            "軽くて辛くない (light and mild)",
        ],
    },
    "Español": {
        "greet": (
            "¡Hola! Antes de mostrar menús, quiero saber qué te apetece. ¿Prefieres algo "
            "caliente y reconfortante, algo ligero y fresco u otra dirección?"
        ),
        "held": (
            "De acuerdo: dejaré las recomendaciones en pausa y haré una pregunta cada vez. "
            "¿Qué sabor o sensación buscas para esta comida?"
        ),
        "meal_direction": (
            "No hace falta elegir todavía. ¿Prefieres algo caliente, algo crujiente o una "
            "comida ligera?"
        ),
        "taste_or_texture": (
            "Perfecto. ¿Qué importa más hoy: un sabor salado o dulce, o una textura "
            "masticable, crujiente o suave?"
        ),
        "budget": "¿Cuál es el presupuesto máximo para la comida?",
        "party_size": "¿Es solo para ti o vais a compartir?",
        "ready_confirmation": "Ya tengo suficiente contexto. ¿Quieres que recomiende menús?",
        "greet_replies": [
            "Caliente y reconfortante (warm and comforting)",
            "Ligero y fresco (light and fresh)",
            "Aún no lo sé (I don't know yet)",
        ],
        "held_replies": [
            "Caliente y salado (warm and savory)",
            "Crujiente y abundante (crispy and filling)",
            "Ligero y suave (light and mild)",
        ],
    },
}

_INPUT_LANGUAGE_NOTICE = {
    "日本語": (" このデモで食事条件を正確に保存するには、英語または韓国語で入力してください。"),
    "Español": (
        " Para que esta demo registre tus necesidades con precisión, escríbelas en "
        "inglés o coreano."
    ),
}

_TARGET_CLARIFICATION_COPY = {
    "English": {
        "explain": "Which food or visible menu would you like me to explain?",
        "compare": (
            "Which food should I compare across restaurants? For visible recommendations, "
            "say first and second."
        ),
    },
    "한국어": {
        "explain": "어떤 음식이나 화면에 보이는 메뉴를 설명해 드릴까요?",
        "compare": "어떤 음식을 가게별로 비교할까요? 화면의 메뉴라면 첫 번째와 두 번째라고 말해 주세요.",
    },
    "日本語": {
        "explain": "どの料理、または画面に表示されているメニューを説明しますか？",
        "compare": "どの料理を店舗ごとに比較しますか？表示中の候補なら first and second と入力してください。",
    },
    "Español": {
        "explain": "¿Qué comida o menú visible quieres que explique?",
        "compare": "¿Qué comida comparo entre restaurantes? Para los menús visibles, escribe first and second.",
    },
}

_NO_COMPARISON_COPY = {
    "English": (
        "I could not find restaurant listings for that food that satisfy your current hard "
        "constraints. Change a constraint or choose another food direction."
    ),
    "한국어": (
        "현재 필수 조건을 모두 만족하는 해당 음식의 가게 메뉴를 찾지 못했어요. "
        "조건을 바꾸거나 다른 음식 방향을 골라 주세요."
    ),
    "日本語": (
        "現在の必須条件をすべて満たす店舗メニューが見つかりませんでした。"
        "条件を変更するか、別の料理を選んでください。"
    ),
    "Español": (
        "No encontré opciones de restaurantes para esa comida que cumplan todas tus "
        "restricciones actuales. Cambia una restricción o elige otra comida."
    ),
}

_NO_EXPLANATION_LISTING_COPY = {
    "English": (
        "I can explain that food generally, but no representative listing satisfies your "
        "current hard constraints. Choose another food or revise a constraint first."
    ),
    "한국어": (
        "음식 자체는 일반적으로 설명할 수 있지만, 현재 필수 조건을 만족하는 대표 메뉴가 "
        "없어요. 다른 음식을 고르거나 조건을 먼저 바꿔 주세요."
    ),
    "日本語": (
        "料理の一般的な説明はできますが、現在の必須条件を満たす代表メニューがありません。"
        "別の料理を選ぶか、先に条件を変更してください。"
    ),
    "Español": (
        "Puedo explicar la comida en general, pero no hay un menú representativo que cumpla "
        "tus restricciones actuales. Elige otra comida o cambia una restricción."
    ),
}

_INFORMATION_UI_COPY = {
    "English": {
        "explanation_title": "What {category} is like",
        "explanation_subtitle": "General synthetic dish Wiki · representative demo listing",
        "explanation_no_listing_subtitle": (
            "General synthetic dish Wiki · no compatible listing shown"
        ),
        "explanation_replies": [
            "Recommend this food when ready",
            "Explain ingredients",
            "Explain another dish",
        ],
        "comparison_title": "{category} comparison",
        "comparison_subtitle": "Synthetic restaurants · shared comparison axes",
        "comparison_replies": [
            "Explain the first menu",
            "Explain another food category",
        ],
    },
    "한국어": {
        "explanation_title": "{category} 알아보기",
        "explanation_subtitle": "합성 음식 Wiki의 일반 정보 · 대표 데모 메뉴",
        "explanation_no_listing_subtitle": "합성 음식 Wiki의 일반 정보 · 조건에 맞는 메뉴는 표시하지 않음",
        "explanation_replies": ["이 음식 추천받기", "재료 설명", "다른 음식 설명 듣기"],
        "comparison_title": "{category} 가게 비교",
        "comparison_subtitle": "합성 가게 · 동일한 비교 기준",
        "comparison_replies": ["첫 번째 메뉴 설명", "다른 음식 종류 설명"],
    },
    "日本語": {
        "explanation_title": "{category}について",
        "explanation_subtitle": "合成料理Wikiの一般情報・代表デモメニュー",
        "explanation_no_listing_subtitle": "合成料理Wikiの一般情報・条件に合うメニューは非表示",
        "explanation_replies": [
            "この料理をおすすめして (Recommend this food)",
            "材料を確認 (Explain ingredients)",
            "別の料理を説明 (Explain another dish)",
        ],
        "comparison_title": "{category}の店舗比較",
        "comparison_subtitle": "合成店舗・共通の比較基準",
        "comparison_replies": [
            "最初のメニューを説明 (Explain the first menu)",
            "別の料理を見る (Explain another food category)",
        ],
    },
    "Español": {
        "explanation_title": "Sobre {category}",
        "explanation_subtitle": "Información general de Wiki sintética · menú demo representativo",
        "explanation_no_listing_subtitle": (
            "Información general de Wiki sintética · sin menú compatible mostrado"
        ),
        "explanation_replies": [
            "Recomienda esta comida (Recommend this food)",
            "Preguntar por ingredientes (Explain ingredients)",
            "Explicar otra comida (Explain another dish)",
        ],
        "comparison_title": "Comparación de {category}",
        "comparison_subtitle": "Restaurantes sintéticos · mismos criterios",
        "comparison_replies": [
            "Explicar la primera opción (Explain the first menu)",
            "Ver otra comida (Explain another food category)",
        ],
    },
}

_CLAIM_STATUS_KO = {
    "CONFIRMED_PRESENT": "확인됨",
    "CONFIRMED_ABSENT": "메뉴 명세상 없음",
    "PRESUMED_PRESENT": "일반적으로 사용",
    "POSSIBLE": "들어갈 수 있음",
    "UNKNOWN": "미확인",
    "CONFLICTING": "근거가 서로 다름",
}

_ALLERGEN_KO = {
    "shellfish_risk": "갑각류·조개류",
    "fish": "생선",
    "milk": "우유",
    "egg": "달걀",
    "peanut": "땅콩",
    "tree_nut": "견과류",
    "wheat": "밀",
    "soy": "대두",
    "sesame": "참깨",
    "cross_contamination_unknown": "교차 접촉",
}

_DIETARY_SAFETY_KO = {
    "contains_animal_product": "동물성 재료",
    "halal_not_verified": "할랄 인증",
    "pork_possible": "돼지고기",
    "vegan_possible": "비건 가능 여부",
    "vegetarian_possible": "채식 가능 여부",
}

_PREPARATION_KO = {
    "assembled_and_mixed": "밥과 고명을 담아 양념에 비벼 먹는 방식",
    "assembled_set": "밥·메인·반찬을 한 상으로 구성하는 방식",
    "baked": "재료를 올려 오븐에 굽는 방식",
    "boiled": "면을 삶는 방식",
    "boiled_and_chilled": "면을 삶아 찬물에 헹구는 방식",
    "boiled_and_mixed": "면을 삶아 양념에 비비는 방식",
    "breaded_and_deep_fried": "빵가루를 입혀 튀기는 방식",
    "breaded_fried_and_assembled": "튀긴 고기와 밥·곁들임을 함께 구성하는 방식",
    "chilled_and_mixed": "삶은 면을 차갑게 식혀 양념에 비비는 방식",
    "chilled_in_broth": "삶은 면을 차가운 육수에 담는 방식",
    "deep_fried": "옷을 입힌 재료를 기름에 튀기는 방식",
    "deep_fried_and_glazed": "튀긴 재료에 양념 소스를 입히는 방식",
    "deep_fried_and_sauced": "튀긴 재료에 소스를 곁들이거나 버무리는 방식",
    "deep_fried_and_seasoned": "튀긴 뒤 가루 양념으로 마무리하는 방식",
    "deep_fried_and_topped": "튀긴 뒤 고명을 올려 마무리하는 방식",
    "filled_and_cooked": "피에 속을 채워 찌거나 삶거나 굽거나 튀기는 방식",
    "formed_and_cooked": "반죽한 재료를 모양 내어 익히는 방식",
    "fried_rolled_and_sliced": "익힌 튀김을 밥·속재료와 말아 써는 방식",
    "frozen_shaved_and_topped": "얼린 우유 베이스를 갈아 토핑을 올리는 방식",
    "griddled": "속을 채운 반죽을 눌러 노릇하게 굽는 방식",
    "grilled": "재료를 노릇하게 굽는 방식",
    "grilled_and_assembled": "구운 재료를 밥·국·반찬과 함께 구성하는 방식",
    "long_simmered": "육수와 재료를 오랫동안 푹 끓이는 방식",
    "marinated_and_grilled": "양념에 재운 재료를 굽는 방식",
    "pan_fried": "기름을 두른 팬에 볶듯 굽는 방식",
    "pressed_and_baked": "반죽을 눌러 와플 틀에 굽는 방식",
    "pressed_baked_and_topped": "눌러 구운 반죽에 토핑을 올리는 방식",
    "rolled_and_sliced": "밥과 속재료를 김에 말아 한입 크기로 써는 방식",
    "served_in_hot_broth": "삶은 면이나 재료를 뜨거운 육수에 담는 방식",
    "shaved_and_topped": "얼음이나 우유 베이스를 곱게 갈아 토핑을 올리는 방식",
    "simmered": "육수와 재료를 함께 끓이는 방식",
    "simmered_and_assembled": "찌개를 끓여 밥·반찬과 함께 구성하는 방식",
    "simmered_and_topped": "소스에 끓인 뒤 토핑을 올리는 방식",
    "stir_fried": "재료를 양념과 함께 볶는 방식",
    "stir_fried_and_assembled": "볶은 재료를 밥·국·반찬과 함께 구성하는 방식",
    "stir_fried_and_mixed": "익힌 재료를 양념과 볶거나 버무리는 방식",
    "stir_fried_then_simmered": "재료를 먼저 볶은 뒤 육수와 함께 끓이는 방식",
    "wok_fried": "센 불의 웍에서 빠르게 볶는 방식",
    "wok_fried_and_mixed": "웍에서 볶은 소스와 면을 섞는 방식",
    "wok_fried_and_sauced": "웍에서 볶은 뒤 소스를 곁들이는 방식",
    "wok_fried_separately": "소스를 따로 볶아 삶은 면과 분리해 내는 방식",
}

_GROUNDED_COPY = {
    "English": {
        "menus": (
            "Based on the needs you shared, the strongest synthetic menu matches are {names}. "
            "I kept menu-specific unknowns and cross-contact limits visible on each card."
        ),
        "categories": (
            "Your current meal needs point toward {names}. I can narrow these directions "
            "before you choose a specific menu."
        ),
        "explanation": (
            "{name}: {description} This is general synthetic Wiki knowledge; "
            "restaurant-specific unknowns remain labelled below."
        ),
        "comparison": "Here are the grounded restaurant trade-offs for the same menu direction.",
        "dietary": (
            "I found dietary evidence that needs attention. Unknown preparation or "
            "cross-contact details are not treated as safe."
        ),
        "options": (
            "Please review {detail}. The server will recheck option availability, price "
            "changes, and dietary conflicts before the demo cart changes."
        ),
        "note": (
            "Please review the displayed Korean order note and its back-translation. It is "
            "not sent anywhere until you explicitly confirm the demo order flow."
        ),
        "address": (
            "I found {count} possible delivery address {matches}. Please confirm one; OCR "
            "output is never treated as an automatically confirmed address."
        ),
        "cart": (
            "The server-calculated synthetic cart has {item_count} {items} and totals {total}. "
            "{missing_count} required checkout {fields}; no real order or charge has been created."
        ),
        "payment": (
            "The mock checkout is {status} for {amount}. This demo cannot make a real charge "
            "or send an order to a restaurant."
        ),
        "order": (
            "The synthetic mock order status is {status}. No restaurant received it and no "
            "real payment was made."
        ),
        "preset": (
            "Here is the server-filtered synthetic demo collection. Every displayed menu "
            "still passed the active hard constraints and retains its unknowns."
        ),
    },
    "한국어": {
        "menus": (
            "공유해 주신 조건을 기준으로 합성 메뉴 중 가장 잘 맞는 후보는 {names}입니다. "
            "메뉴별 미확인 정보와 교차 접촉 한계는 각 카드에 그대로 표시했어요."
        ),
        "categories": (
            "현재 식사 조건에는 {names} 방향이 맞아요. 구체적인 메뉴를 고르기 전에 "
            "이 방향들을 더 좁힐 수 있어요."
        ),
        "explanation": (
            "{name}에 대한 합성 음식 Wiki 근거예요. {description} "
            "가게별로 확인되지 않은 내용은 아래에 따로 표시했어요."
        ),
        "comparison": "같은 메뉴 방향에 대한 가게별 근거 기반 차이를 보여드릴게요.",
        "dietary": (
            "주의해야 할 식단 근거가 있어요. 조리법이나 교차 접촉 여부가 "
            "확인되지 않았다면 안전하다고 판정하지 않아요."
        ),
        "options": (
            "{detail}을(를) 확인해 주세요. 데모 장바구니를 바꾸기 전에 서버가 옵션 "
            "판매 여부, 가격, 식단 충돌을 다시 확인합니다."
        ),
        "note": (
            "표시된 한국어 요청사항과 역번역을 확인해 주세요. 데모 주문 흐름을 "
            "명시적으로 확정하기 전에는 어디에도 전송되지 않아요."
        ),
        "address": (
            "배달지 후보 {count}개를 찾았어요. 하나를 확인해 주세요. OCR 결과는 "
            "자동으로 확정된 주소로 처리하지 않아요."
        ),
        "cart": (
            "서버가 계산한 합성 장바구니에는 메뉴 {item_count}개가 있고 합계는 {total}입니다. "
            "결제 필수 항목 {missing_count}개가 남아 있으며 실제 주문이나 청구는 생성되지 않았어요."
        ),
        "payment": (
            "목업 결제 상태는 {status}, 금액은 {amount}입니다. 이 데모는 실제로 "
            "결제하거나 가게에 주문을 보낼 수 없어요."
        ),
        "order": (
            "합성 목업 주문 상태는 {status}입니다. 실제 가게에 전송되지 않았고 "
            "실제 결제도 이루어지지 않았어요."
        ),
        "preset": (
            "서버가 현재 조건으로 필터링한 합성 데모 목록입니다. 표시된 모든 "
            "메뉴는 현재 필수 조건을 통과했고 미확인 정보도 그대로 보여줍니다."
        ),
    },
    "日本語": {
        "menus": (
            "お伝えいただいた条件に基づく合成メニューの有力候補は {names} です。"
            "メニュー固有の未確認事項と交差接触の制限は各カードに表示しています。"
        ),
        "categories": (
            "現在の食事条件には {names} の方向が合います。具体的なメニューを"
            "選ぶ前に、さらに絞り込めます。"
        ),
        "explanation": (
            "{name} についての合成食品 Wiki の一般説明です。"
            "店舗固有の未確認事項は下に明示しています。"
        ),
        "comparison": "同じメニューについて、根拠のある店舗間の違いを示します。",
        "dietary": (
            "注意が必要な食事根拠があります。調理方法や交差接触が未確認の場合、"
            "安全とは判定しません。"
        ),
        "options": (
            "{detail} を確認してください。デモカートを変更する前に、サーバーが"
            "オプションの提供状況、価格、食事条件との衝突を再確認します。"
        ),
        "note": (
            "表示された韓国語の注文メモと逆翻訳を確認してください。"
            "デモ注文を明示的に確定するまで、どこにも送信されません。"
        ),
        "address": (
            "配達先候補が {count} 件見つかりました。一つ選んでください。OCR 出力は"
            "自動的に確定済み住所として扱いません。"
        ),
        "cart": (
            "サーバー計算の合成カートには {item_count} 件、合計 {total} が入っています。"
            "必須の決済項目が {missing_count} 件残っており、実際の注文や請求は作成されていません。"
        ),
        "payment": (
            "モック決済の状態は {status}、金額は {amount} です。このデモでは"
            "実際の請求や店舗への注文送信は行いません。"
        ),
        "order": (
            "合成モック注文の状態は {status} です。店舗には送信されておらず、"
            "実際の支払いも行われていません。"
        ),
        "preset": (
            "サーバーが現在の必須条件で絞り込んだ合成デモコレクションです。"
            "表示メニューには未確認事項もそのまま残しています。"
        ),
    },
    "Español": {
        "menus": (
            "Según las necesidades que compartiste, las mejores coincidencias del catálogo "
            "sintético son {names}. Cada tarjeta mantiene visibles los datos desconocidos y "
            "los límites de contacto cruzado."
        ),
        "categories": (
            "Tus necesidades actuales apuntan a {names}. Puedo acotar estas direcciones antes "
            "de que elijas un menú concreto."
        ),
        "explanation": (
            "Esta es una explicación general de {name} del Wiki sintético; los datos "
            "desconocidos de cada restaurante siguen indicados abajo."
        ),
        "comparison": "Estas son las diferencias fundamentadas entre restaurantes para el mismo menú.",
        "dietary": (
            "Encontré evidencia alimentaria que requiere atención. Una preparación o un "
            "contacto cruzado desconocidos no se consideran seguros."
        ),
        "options": (
            "Revisa {detail}. Antes de cambiar el carrito demo, el servidor volverá a comprobar "
            "la disponibilidad, el precio y los conflictos alimentarios."
        ),
        "note": (
            "Revisa la nota del pedido en coreano y su traducción inversa. No se envía a ningún "
            "sitio hasta que confirmes expresamente el flujo del pedido demo."
        ),
        "address": (
            "Encontré {count} posibles coincidencias de dirección. Confirma una; el resultado "
            "del OCR nunca se trata como una dirección confirmada automáticamente."
        ),
        "cart": (
            "El carrito sintético calculado por el servidor contiene {item_count} artículos y "
            "suma {total}. Quedan {missing_count} campos obligatorios; no se ha creado ningún "
            "pedido ni cargo real."
        ),
        "payment": (
            "El pago simulado está {status} por {amount}. Esta demo no puede hacer un cargo real "
            "ni enviar un pedido a un restaurante."
        ),
        "order": (
            "El estado del pedido simulado sintético es {status}. Ningún restaurante lo ha "
            "recibido y no se ha realizado ningún pago real."
        ),
        "preset": (
            "Esta es la colección demo sintética filtrada por el servidor. Todos los menús "
            "mostrados superaron las restricciones activas y conservan sus datos desconocidos."
        ),
    },
}


class ChatService:
    def __init__(
        self,
        repository: YobiRepository,
        settings: Settings,
        demo_control: DemoControl,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.demo_control = demo_control
        self.agent = AgentLoop(settings)
        self.dialogue = DialogueEngine()
        self.grounding = GroundedResponseValidator()
        self.logger = logging.getLogger("yobi")
        self._session_locks: dict[str, LockType] = {}
        self._session_locks_guard = Lock()

    def _session_lock(self, session_id: str) -> LockType:
        with self._session_locks_guard:
            return self._session_locks.setdefault(session_id, Lock())

    @contextmanager
    def session_guard(self, session_id: str) -> Iterator[None]:
        """Serialise message and UI-event transitions for one deployed app process."""

        with self._session_lock(session_id):
            yield

    @staticmethod
    def _request_message_ids(session_id: str, request_id: str) -> tuple[str, str]:
        digest = hashlib.sha256(f"{session_id}:{request_id}".encode()).hexdigest()[:40]
        return f"msg_u_{digest}", f"msg_a_{digest}"

    def _replayed_turn(
        self,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        user_text: str,
        request_id: str,
        intent: Literal["weekly_ranking", "kpop_demon_hunters"] | None,
    ) -> AssistantTurn | None:
        messages = self.repository.list_messages(session_id)
        user_message = next(
            (message for message in messages if message["message_id"] == user_message_id),
            None,
        )
        assistant_message = next(
            (message for message in messages if message["message_id"] == assistant_message_id),
            None,
        )
        if user_message is None and assistant_message is None:
            return None
        if user_message is None or assistant_message is None:
            # commit_chat_turn writes both rows in one transaction. A partial pair is
            # therefore corruption, not a request that is safe to execute again.
            raise RuntimeError("CHAT_REQUEST_RECORD_INCOMPLETE")
        user_metadata = user_message.get("safe_metadata")
        if not isinstance(user_metadata, dict):
            raise RuntimeError("CHAT_REQUEST_RECORD_INCOMPLETE")
        if (
            user_message.get("content") != user_text
            or user_metadata.get("client_request_id") != request_id
            or user_metadata.get("intent") != intent
        ):
            raise ValueError("CHAT_REQUEST_ID_REUSED")
        assistant_metadata = assistant_message.get("safe_metadata")
        if not isinstance(assistant_metadata, dict):
            raise RuntimeError("CHAT_REQUEST_RECORD_INCOMPLETE")
        try:
            return AssistantTurn.model_validate(assistant_metadata)
        except Exception as exc:
            raise RuntimeError("CHAT_REQUEST_RECORD_INCOMPLETE") from exc

    def respond(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        intent: Literal["weekly_ranking", "kpop_demon_hunters"] | None = None,
        *,
        request_id: str | None = None,
    ) -> AssistantTurn:
        # The deployed app owns one shared ChatService instance. Serialising each
        # session prevents a second request from running a cart mutation against a
        # state version that another request is already advancing.
        with self.session_guard(session.session_id):
            effective_request_id = request_id or f"server-{uuid4().hex}"
            user_message_id, assistant_message_id = self._request_message_ids(
                session.session_id, effective_request_id
            )
            replayed = self._replayed_turn(
                session.session_id,
                user_message_id,
                assistant_message_id,
                user_text,
                effective_request_id,
                intent,
            )
            if replayed is not None:
                return replayed
            current = self.repository.get_session(session.session_id)
            if current is None:
                raise KeyError("SESSION_NOT_FOUND")
            if current.state_version != session.state_version:
                raise RuntimeError("CHAT_STATE_VERSION_CONFLICT")
            return self._respond_locked(
                current,
                profile,
                user_text,
                effective_request_id,
                user_message_id,
                assistant_message_id,
                intent,
            )

    def _respond_locked(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        request_id: str,
        user_message_id: str,
        assistant_message_id: str,
        intent: Literal["weekly_ranking", "kpop_demon_hunters"] | None = None,
    ) -> AssistantTurn:
        started = monotonic()
        user_created_at = datetime.now(timezone.utc)
        safe_error_code: str | None = None
        fallback_reason: FallbackReason | None = None
        dialogue_update = self.dialogue.update(session.meal_need_state, profile, user_text)
        need_state = dialogue_update.state
        if (
            need_state.pending_information_request is not None
            and dialogue_update.delta.dialogue_act != DialogueAct.COLLECT_NEEDS
            and not (
                need_state.pending_information_request == "compare"
                and dialogue_update.delta.dialogue_act == DialogueAct.COMPARE
            )
        ):
            need_state.pending_information_request = None
        if need_state.selected_menu_id is None and session.selected_menu_id:
            # Preserve selections created by pre-005 sessions until the user explicitly
            # changes them through the snapshot event contract.
            need_state.selected_menu_id = session.selected_menu_id
        if not need_state.service_area_id:
            need_state.service_area_id = self.repository.get_session_service_area(
                session.session_id
            )
        readiness = dialogue_update.readiness
        preset_turn = self._preset_turn(session, profile, intent, need_state) if intent else None
        use_fallback = not self.agent.configured or self.demo_control.mode in {
            "force_fallback",
            "force_genai_timeout",
        }
        if preset_turn is not None:
            turn = preset_turn
            use_fallback = False
            if turn.cards:
                turn.dialogue_act = DialogueAct.RECOMMEND
        elif pending_turn := self._pending_information_turn(
            session,
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = pending_turn
            use_fallback = False
        elif selection_turn := self._natural_snapshot_selection_turn(
            session,
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = selection_turn
            use_fallback = False
        elif rejection_turn := self._natural_snapshot_rejection_turn(
            session,
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = rejection_turn
            use_fallback = False
        elif comparison_turn := self._natural_snapshot_comparison_turn(
            session,
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = comparison_turn
            use_fallback = False
        elif category_comparison_turn := self._category_comparison_turn(
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = category_comparison_turn
            use_fallback = False
        elif dialogue_update.delta.dialogue_act in {
            DialogueAct.REQUEST_EXPLANATION,
            DialogueAct.COLLECT_NEEDS,
        } and (reference_turn := self._snapshot_reference_turn(session, profile, user_text)):
            turn = reference_turn
            use_fallback = False
        elif comparison_turn := self._stored_comparison_turn(
            session,
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = comparison_turn
            use_fallback = False
        elif explanation_turn := self._generic_explanation_turn(
            profile,
            user_text,
            need_state,
            dialogue_update.delta.dialogue_act,
        ):
            turn = explanation_turn
            use_fallback = False
        elif dialogue_update.delta.dialogue_act in {
            DialogueAct.REQUEST_EXPLANATION,
            DialogueAct.COMPARE,
        } and self._catalog_category(user_text) is None:
            turn = self._target_clarification_turn(
                profile,
                dialogue_update.delta.dialogue_act,
                need_state,
            )
            use_fallback = False
        elif not readiness.may_recommend and dialogue_update.delta.dialogue_act not in {
            DialogueAct.REQUEST_EXPLANATION,
            DialogueAct.COMPARE,
            DialogueAct.SELECT,
            DialogueAct.ORDER_ACTION,
        }:
            turn = self._needs_collection_turn(
                profile, dialogue_update.delta.dialogue_act, readiness
            )
            # Missing-information prompts are a server-owned state-machine contract.
            # Calling a model here would add cost and latency while its prose is
            # intentionally discarded for grounding safety.
            use_fallback = False
        elif not use_fallback:
            try:
                result = self.agent.run(
                    user_text,
                    self._dynamic_context(
                        session,
                        profile,
                        need_state,
                        readiness,
                        dialogue_update.delta.dialogue_act,
                    ),
                    ToolRegistry(
                        self.repository,
                        profile,
                        session.session_id,
                        meal_need_state=need_state,
                        mutation_idempotency_key=f"agent_{user_message_id}",
                        user_query=user_text,
                    ),
                    dialogue_act=dialogue_update.delta.dialogue_act,
                )
                turn = self._turn_from_tool_results(
                    session,
                    result.text,
                    result.tool_results,
                    requested_act=dialogue_update.delta.dialogue_act,
                    source_query=user_text,
                )
                if not result.tool_results or not turn.cards:
                    raise RuntimeError("GENAI_GROUNDING_REQUIRED")
                turn.text = self._server_grounded_text(turn, profile.preferred_language)
                try:
                    self.grounding.validate(
                        turn,
                        result.referenced_menu_ids,
                        result.referenced_claim_ids,
                        result.referenced_passage_ids,
                        result.grounding_scope,
                        result.uncertainty_codes,
                    )
                except Exception as exc:
                    mutation_names = {
                        "update_cart",
                        "update_delivery_preferences",
                        "create_mock_checkout",
                    }
                    if not any(name in mutation_names for name, _ in result.tool_results):
                        raise
                    fallback_reason = self._classify_fallback(exc)
                    turn.fallback_used = True
                    turn.fallback_reason = fallback_reason
                    safe_error_code = fallback_reason.value
                if result.provider_error_code is not None:
                    fallback_reason = self._classify_fallback(
                        RuntimeError(result.provider_error_code.value)
                    )
                    turn.fallback_used = True
                    turn.fallback_reason = fallback_reason
                    safe_error_code = result.provider_error_code.value
            except Exception as exc:
                if not self.settings.demo_fallback_enabled:
                    raise
                fallback_reason = self._classify_fallback(exc)
                safe_error_code = (
                    exc.code.value
                    if isinstance(exc, GenAIProviderError)
                    else fallback_reason.value
                )
                use_fallback = True
        if use_fallback:
            fallback_turn: AssistantTurn | None = None
            if dialogue_update.delta.dialogue_act == DialogueAct.ORDER_ACTION:
                fallback_turn = self._deterministic_order_action_turn(
                    session,
                    profile,
                    user_text,
                    need_state,
                    idempotency_key=f"agent_{user_message_id}",
                )
            turn = fallback_turn or self._deterministic_turn(
                session, profile, user_text, need_state
            )
            fallback_language = self._narrative_language(profile.preferred_language)
            if turn.cards and fallback_language in {"한국어", "日本語", "Español"}:
                turn.text = self._server_grounded_text(turn, fallback_language)
            turn.fallback_used = True
            fallback_reason = fallback_reason or self._classify_fallback(None)
            turn.fallback_reason = fallback_reason
            safe_error_code = safe_error_code or fallback_reason.value

        if turn.dialogue_act == DialogueAct.COLLECT_NEEDS:
            if any(
                card.type
                in {"menu_recommendations", "category_recommendations", "preset_collection"}
                for card in turn.cards
            ):
                turn.dialogue_act = DialogueAct.RECOMMEND
            elif readiness.status.value == "HELD":
                turn.dialogue_act = DialogueAct.HOLD_RECOMMENDATION
        turn.readiness = readiness
        # The assistant row, snapshot FK, and replay lookup share one stable ID for
        # this client request. The hash prevents the client key itself from leaking.
        turn.message_id = assistant_message_id
        snapshot = self._recommendation_snapshot(session, turn, need_state, user_text)
        if snapshot is not None:
            turn.recommendation_result = snapshot.result
            turn.recommendation_snapshot_id = snapshot.snapshot_id
            for candidate in snapshot.result.candidates:
                if candidate.menu_id not in need_state.shown_menu_ids:
                    need_state.shown_menu_ids.append(candidate.menu_id)
        updated_session = self.repository.commit_chat_turn(
            session.session_id,
            session.state_version,
            user_message_id,
            user_text,
            user_created_at,
            turn,
            need_state,
            turn.dialogue_act,
            snapshot,
            request_id=request_id,
            intent=intent,
        )
        turn.state_version = updated_session.state_version
        evidence_ids = [
            str(item.get("evidence_id"))
            for card in turn.cards
            for item in card.data.get("evidence", [])
            if isinstance(item, dict) and item.get("evidence_id")
        ]
        latency_ms = int((monotonic() - started) * 1000)
        try:
            self.repository.record_audit(
                session.session_id,
                "assistant_turn",
                user_text,
                evidence_ids,
                "OK",
                latency_ms,
                turn.fallback_used,
                safe_error_code,
            )
        except Exception:
            # The dialogue turn is already committed. Observability must never turn a
            # successful user-visible mutation into a retryable application failure.
            log_event(
                self.logger,
                event="assistant_turn_audit_failed",
                session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
                safe_error_code="AUDIT_WRITE_FAILED",
            )
        log_event(
            self.logger,
            request_id=None,
            session_id_hash=hashlib.sha256(session.session_id.encode()).hexdigest(),
            endpoint="assistant_turn",
            latency_ms=latency_ms,
            tool="assistant_turn",
            status="OK",
            evidence_count=len(evidence_ids),
            fallback=turn.fallback_used,
            safe_error_code=safe_error_code,
        )
        return turn

    def _deterministic_order_action_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        *,
        idempotency_key: str,
    ) -> AssistantTurn | None:
        """Preserve cart intent when generation is unavailable.

        The fallback never invents menu or option identifiers. It uses the
        server-selected menu and persisted option events, while the repository
        reapplies live safety, availability, and price validation.
        """

        lowered = user_text.lower()
        add_requested = ("cart" in lowered and "add" in lowered) or (
            "장바구니" in lowered and any(marker in lowered for marker in ("담", "추가", "넣"))
        )
        if add_requested:
            if not state.selected_menu_id:
                return self._make_turn(
                    "Please choose one of the saved recommendation cards first. I did not "
                    "guess which menu you meant or change the demo cart.",
                    ChatState.MENU_SELECTION,
                    [],
                    False,
                    ["Show my latest recommendations", "Recommend again"],
                    dialogue_act=DialogueAct.ORDER_ACTION,
                )
            menu = self.repository.get_menu(state.selected_menu_id, profile)
            if menu is None:
                return self._make_turn(
                    "That selected menu is no longer available, so I did not change the demo "
                    "cart. Please choose another current recommendation.",
                    ChatState.MENU_SELECTION,
                    [],
                    False,
                    ["Recommend again"],
                    dialogue_act=DialogueAct.ORDER_ACTION,
                )
            option_groups = self.repository.get_options(menu.menu_id)
            available_by_group = {
                group.option_group_id: {
                    item.option_item_id for item in group.items if item.available
                }
                for group in option_groups
            }
            unsatisfied = []
            for group in option_groups:
                chosen = {
                    option_id
                    for option_id in state.option_selections.get(group.option_group_id, [])
                    if option_id in available_by_group[group.option_group_id]
                }
                if len(chosen) < group.min_select or len(chosen) > group.max_select:
                    unsatisfied.append(group)
            if unsatisfied:
                return self._make_turn(
                    f"Before I can add {menu.name_en}, please complete its required option "
                    "choices. Nothing was added to the demo cart yet.",
                    ChatState.MENU_OPTIONS,
                    [
                        Card(
                            type="option_question",
                            title=f"Required options for {menu.name_en}",
                            subtitle="Server-validated choices",
                            data={
                                "menu": menu.model_dump(mode="json"),
                                "option_groups": [
                                    group.model_dump(mode="json") for group in unsatisfied
                                ],
                            },
                        )
                    ],
                    False,
                    dialogue_act=DialogueAct.ORDER_ACTION,
                )
            try:
                cart = self.repository.add_cart_item(
                    session.session_id,
                    CartItemInput(
                        menu_id=menu.menu_id,
                        option_item_ids=self._selected_option_ids(menu.menu_id, state),
                    ),
                    agent_request_key=idempotency_key,
                )
            except ValueError:
                return self._make_turn(
                    f"I did not add {menu.name_en}. A current menu, option, dietary, or "
                    "delivery constraint needs review first; I kept every constraint active.",
                    ChatState.MENU_OPTIONS,
                    [
                        Card(
                            type="option_question",
                            title=f"Review options for {menu.name_en}",
                            subtitle="No cart change was made",
                            data={
                                "menu": menu.model_dump(mode="json"),
                                "option_groups": [
                                    group.model_dump(mode="json") for group in option_groups
                                ],
                            },
                        )
                    ],
                    False,
                    ["Choose different options", "Recommend another menu"],
                    dialogue_act=DialogueAct.ORDER_ACTION,
                )
            return self._make_turn(
                f"I added {menu.name_en} to the synthetic demo cart and rechecked its "
                "current price, options, and active dietary constraints.",
                ChatState.ORDER_REVIEW,
                [
                    Card(
                        type="cart_summary",
                        title="Server-calculated demo cart",
                        subtitle="Demo only · no restaurant order or real charge",
                        data={"cart": cart.model_dump(mode="json")},
                    )
                ],
                False,
                ["Review delivery details", "Continue to mock checkout"],
                dialogue_act=DialogueAct.ORDER_ACTION,
            )

        if any(
            marker in lowered
            for marker in (
                "cart",
                "장바구니",
                "checkout",
                "payment",
                "결제",
                "order status",
            )
        ):
            cart = self.repository.get_cart(session.session_id)
            return self._make_turn(
                "Here is the current synthetic demo cart. Review the required delivery and "
                "option fields before starting mock checkout; this is not a real payment.",
                ChatState.ORDER_REVIEW,
                [
                    Card(
                        type="cart_summary",
                        title="Server-calculated demo cart",
                        subtitle="Mock checkout only",
                        data={"cart": cart.model_dump(mode="json")},
                    )
                ],
                False,
                dialogue_act=DialogueAct.ORDER_ACTION,
            )
        return None

    def _recommendation_snapshot(
        self,
        session: Session,
        turn: AssistantTurn,
        need_state: MealNeedState,
        user_text: str,
    ) -> RecommendationSnapshot | None:
        if turn.dialogue_act != DialogueAct.RECOMMEND:
            return None
        menus: list[dict[str, object]] = []

        def visit(value: object) -> None:
            if isinstance(value, dict):
                if value.get("menu_id") and value.get("merchant_id"):
                    menus.append({str(key): item for key, item in value.items()})
                    return
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for card in turn.cards:
            if card.type in {"menu_recommendations", "preset_collection"}:
                visit(card.data)
        unique: list[dict[str, object]] = []
        seen: set[str] = set()
        for menu in menus:
            menu_id = str(menu["menu_id"])
            if menu_id in seen:
                continue
            seen.add(menu_id)
            unique.append(menu)
        if not unique:
            return None
        snapshot_id = f"snapshot_{uuid4().hex}"

        def string_list(value: object) -> list[str]:
            return [str(item) for item in value] if isinstance(value, list) else []

        def score(value: object, default: float) -> float:
            return float(value) if isinstance(value, (int, float)) else default

        candidates = [
            RecommendationCandidate(
                menu_id=str(menu["menu_id"]),
                merchant_id=str(menu["merchant_id"]),
                rank=index,
                score=score(menu.get("semantic_score"), max(0.0, 1.0 - (index - 1) * 0.05)),
                match_reasons=string_list(menu.get("match_reasons")),
                risk_hints=string_list(menu.get("risk_hints")),
                evidence_ids=string_list(menu.get("evidence_ids")),
                claim_ids=string_list(menu.get("grounded_claim_ids")),
                passage_ids=string_list(menu.get("grounded_passage_ids")),
            )
            for index, menu in enumerate(unique, start=1)
        ]
        result = RecommendationResult(
            snapshot_id=snapshot_id,
            candidates=candidates,
            query_summary=self._need_summary(need_state, user_text),
            grounded_claim_ids=list(
                dict.fromkeys(
                    claim_id
                    for candidate in candidates
                    for claim_id in (*candidate.evidence_ids, *candidate.claim_ids)
                )
            ),
            grounded_passage_ids=list(
                dict.fromkeys(
                    passage_id for candidate in candidates for passage_id in candidate.passage_ids
                )
            ),
        )
        return RecommendationSnapshot(
            snapshot_id=snapshot_id,
            session_id=session.session_id,
            assistant_message_id=turn.message_id,
            state_version=session.state_version + 1,
            meal_need_state=need_state,
            result=result,
            cards=[card.model_dump(mode="json") for card in turn.cards],
            created_at=turn.created_at,
        )

    @staticmethod
    def _need_summary(state: MealNeedState, fallback: str) -> str:
        parts: list[str] = []
        if state.temperature_preferences:
            parts.append("/".join(state.temperature_preferences))
        if state.flavor_preferences:
            parts.append("/".join(state.flavor_preferences))
        if state.texture_preferences:
            parts.append("/".join(state.texture_preferences))
        if state.preferred_categories:
            parts.append("prefers " + "/".join(state.preferred_categories))
        if state.excluded_categories:
            parts.append("no " + "/".join(state.excluded_categories))
        if state.excluded_ingredients:
            parts.append("without " + "/".join(state.excluded_ingredients))
        if state.dietary_rules:
            parts.append(
                "dietary rules " + "/".join(rule.replace("_", " ") for rule in state.dietary_rules)
            )
        if state.max_spiciness is not None:
            parts.append(f"maximum spice {state.max_spiciness} of 3")
        if state.budget_krw:
            parts.append(f"under KRW {state.budget_krw}")
        if state.party_size:
            parts.append(f"for {state.party_size}")
        return "; ".join(parts) or fallback[:300]

    @staticmethod
    def _active_need_badges(state: MealNeedState) -> list[str]:
        """Return display labels only for constraints stored by the server."""

        badges: list[str] = []
        if state.budget_krw is not None:
            badges.append(f"Under ₩{state.budget_krw:,}")
        if state.max_spiciness is not None:
            badges.append(f"Maximum spice {state.max_spiciness} of 3")
        badges.extend(
            f"No {ingredient.replace('_', ' ')}" for ingredient in state.excluded_ingredients
        )
        badges.extend(rule.replace("_", " ") for rule in state.dietary_rules)
        return list(dict.fromkeys(badges))

    def _selected_option_ids(self, menu_id: str, state: MealNeedState) -> list[str]:
        allowed = {
            item.option_item_id
            for group in self.repository.get_options(menu_id)
            for item in group.items
        }
        return list(
            dict.fromkeys(
                option_id
                for selected in state.option_selections.values()
                for option_id in selected
                if option_id in allowed
            )
        )

    def _menu_still_satisfies_active_constraints(
        self,
        menu_id: str,
        profile: Profile,
        state: MealNeedState,
    ) -> bool:
        """Revalidate a saved menu without making the new utterance a ranking query.

        A recommendation snapshot can contain a menu that ranks below the global
        retrieval cap for follow-up text such as ``choose the first menu``.  That is
        not a hard-constraint failure.  The merchant-scoped path evaluates every
        menu in the saved candidate's merchant and applies the same availability,
        budget, party, dietary, allergy, and service-area rules without unrelated
        semantic truncation.
        """

        menu = self.repository.get_menu(menu_id, profile)
        if menu is None:
            return False
        return any(
            candidate.menu_id == menu_id
            for candidate in self.repository.list_merchant_menus(
                menu.merchant_id,
                profile,
                state.rejected_menu_ids,
                limit=150,
                meal_need_state=state,
            )
        )

    def _stored_comparison_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        if requested_act != DialogueAct.COMPARE or len(state.compared_menu_ids) < 2:
            return None
        menus = [
            menu
            for menu_id in state.compared_menu_ids
            if self._menu_still_satisfies_active_constraints(menu_id, profile, state)
            and (menu := self.repository.get_menu(menu_id, profile)) is not None
        ]
        if len(menus) < 2:
            return self._make_turn(
                "Those earlier menus no longer both satisfy the current hard constraints. "
                "Would you like me to build a new comparison?",
                ChatState.CLARIFICATION,
                [],
                False,
                ["Build a new comparison", "Review my constraints"],
                dialogue_act=DialogueAct.COLLECT_NEEDS,
            )
        comparisons = [
            {
                "merchant_id": menu.merchant_id,
                "merchant_name": menu.merchant_name,
                "menu_id": menu.menu_id,
                "menu_name": menu.name_en,
                "price": menu.price,
                "delivery_fee": menu.delivery_fee,
                "eta": f"{menu.eta_min}-{menu.eta_max} min",
                "portion": f"Serves {menu.serves_min}-{menu.serves_max}",
                "flavor": menu.description,
                "packaging_signal": "Not used for safety or ranking in this demo",
                "dietary_status": menu.evidence_status.value,
                "dietary_note": "; ".join(menu.risk_hints)
                or "Menu-specific unknowns still require confirmation.",
                "best_for": "; ".join(menu.match_reasons),
                "evidence_ids": menu.evidence_ids,
                "menu": menu.model_dump(mode="json"),
                "is_synthetic": True,
            }
            for menu in menus
        ]
        names = " and ".join(menu.name_en for menu in menus)
        turn = self._make_turn(
            f"Here is a server-checked comparison of {names}; prices, delivery details, "
            "active constraints, and unresolved dietary details use the same saved candidates.",
            ChatState.MERCHANT_COMPARISON,
            [
                Card(
                    type="merchant_comparison",
                    title="Compare the saved recommendations",
                    subtitle="Synthetic demo menus · current constraints reapplied",
                    data={"merchants": comparisons},
                )
            ],
            False,
            ["Choose the first menu", "Choose the second menu", "Show another direction"],
            dialogue_act=DialogueAct.COMPARE,
        )
        snapshot = self.repository.get_recommendation_snapshot(session.session_id)
        if snapshot is not None and set(state.compared_menu_ids).issubset(
            {candidate.menu_id for candidate in snapshot.result.candidates}
        ):
            turn.recommendation_snapshot_id = snapshot.snapshot_id
        return turn

    def _natural_snapshot_selection_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        if requested_act != DialogueAct.SELECT:
            return None
        lowered = user_text.lower()
        ordinal_markers = (
            "first menu",
            "second menu",
            "third menu",
            "1st menu",
            "2nd menu",
            "3rd menu",
            "첫 번째 메뉴",
            "두 번째 메뉴",
            "세 번째 메뉴",
        )
        if not any(marker in lowered for marker in ordinal_markers):
            return None
        snapshot = self.repository.get_recommendation_snapshot(session.session_id)
        if snapshot is None:
            return None
        if any(marker in lowered for marker in ("second", "2nd", "두 번째")):
            index = 1
        elif any(marker in lowered for marker in ("third", "3rd", "세 번째")):
            index = 2
        else:
            index = 0
        if index >= len(snapshot.result.candidates):
            return None
        candidate = snapshot.result.candidates[index]
        if not self._menu_still_satisfies_active_constraints(candidate.menu_id, profile, state):
            return self._make_turn(
                "That earlier menu no longer satisfies the active hard constraints, so I did "
                "not select it. Would you like a new recommendation?",
                ChatState.CLARIFICATION,
                [],
                False,
                ["Recommend again", "Review my constraints"],
                dialogue_act=DialogueAct.COLLECT_NEEDS,
            )
        menu = self.repository.get_menu(candidate.menu_id, profile)
        if menu is None:
            return None
        state.selected_menu_id = candidate.menu_id
        option_groups = [
            group.model_dump(mode="json")
            for group in self.repository.get_options(candidate.menu_id)
        ]
        cards = (
            [
                Card(
                    type="option_question",
                    title=f"Options for {menu.name_en}",
                    subtitle="Selection saved from the latest recommendation snapshot",
                    data={"menu": menu.model_dump(mode="json"), "option_groups": option_groups},
                )
            ]
            if option_groups
            else []
        )
        return self._make_turn(
            f"I selected the {self._ordinal(index + 1)} saved recommendation, {menu.name_en}. "
            "Please review its required options before adding it to the demo cart.",
            ChatState.MENU_SELECTION,
            cards,
            False,
            dialogue_act=DialogueAct.SELECT,
        )

    def _natural_snapshot_rejection_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        if requested_act != DialogueAct.REJECT:
            return None
        snapshot = self.repository.get_recommendation_snapshot(session.session_id)
        if snapshot is None or not snapshot.result.candidates:
            return None
        lowered = user_text.lower()
        if any(marker in lowered for marker in ("second", "2nd", "두 번째")):
            index = 1
        elif any(marker in lowered for marker in ("third", "3rd", "세 번째")):
            index = 2
        elif any(marker in lowered for marker in ("first", "1st", "첫 번째")):
            index = 0
        elif state.selected_menu_id:
            index = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(snapshot.result.candidates)
                    if candidate.menu_id == state.selected_menu_id
                ),
                0,
            )
        else:
            # “Show another” refers to the leading item in the latest server-owned
            # snapshot. We never infer from a model-written menu name.
            index = 0
        if index >= len(snapshot.result.candidates):
            return self._make_turn(
                "That saved recommendation did not contain that many menus. Which visible "
                "menu would you like me to remove?",
                ChatState.CLARIFICATION,
                [],
                False,
                dialogue_act=DialogueAct.REJECT,
            )
        rejected_id = snapshot.result.candidates[index].menu_id
        if rejected_id not in state.rejected_menu_ids:
            state.rejected_menu_ids.append(rejected_id)
        if state.selected_menu_id == rejected_id:
            state.selected_menu_id = None
        rejected_menu = self.repository.get_menu(rejected_id, profile)
        replacement = self._deterministic_turn(session, profile, user_text, state)
        if any(
            card.type in {"menu_recommendations", "category_recommendations", "preset_collection"}
            for card in replacement.cards
        ):
            replacement.dialogue_act = DialogueAct.RECOMMEND
            name = rejected_menu.name_en if rejected_menu else "that menu"
            replacement.text = (
                f"I removed {name} from this session's candidates and kept every current "
                f"constraint active. {replacement.text}"
            )
        else:
            replacement.dialogue_act = DialogueAct.REJECT
        return replacement

    def _natural_snapshot_comparison_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        if requested_act != DialogueAct.COMPARE:
            return None
        snapshot = self.repository.get_recommendation_snapshot(session.session_id)
        if snapshot is None or len(snapshot.result.candidates) < 2:
            return None
        lowered = user_text.lower()
        referenced_indices: list[int] = []
        for index, markers in (
            (0, ("first", "1st", "첫 번째")),
            (1, ("second", "2nd", "두 번째")),
            (2, ("third", "3rd", "세 번째")),
        ):
            if any(marker in lowered for marker in markers):
                referenced_indices.append(index)
        ordinal_reference = bool(referenced_indices)
        if not referenced_indices:
            for index, candidate in enumerate(snapshot.result.candidates):
                menu = self.repository.get_menu(candidate.menu_id, profile)
                if menu is None:
                    continue
                compact = lowered.replace(" ", "")
                if (
                    menu.name_en.lower() in lowered
                    or menu.name_ko.replace(" ", "") in compact
                    or menu.category.lower() in lowered
                ):
                    referenced_indices.append(index)
            referenced_indices = list(dict.fromkeys(referenced_indices))
        if len(referenced_indices) < 2 and not ordinal_reference:
            if self._catalog_category(user_text) is not None:
                return None
            referenced_indices = []
        if not referenced_indices:
            referenced_indices = list(range(min(3, len(snapshot.result.candidates))))
        referenced_menu_ids = list(
            dict.fromkeys(
                snapshot.result.candidates[index].menu_id
                for index in referenced_indices
                if index < len(snapshot.result.candidates)
            )
        )
        if state.pending_information_request == "compare":
            referenced_menu_ids = list(
                dict.fromkeys([*state.compared_menu_ids, *referenced_menu_ids])
            )
        state.compared_menu_ids = referenced_menu_ids
        if len(state.compared_menu_ids) < 2:
            state.pending_information_request = "compare"
            return self._make_turn(
                "Please name at least two visible recommendations to compare.",
                ChatState.CLARIFICATION,
                [],
                False,
                dialogue_act=DialogueAct.COMPARE,
            )
        state.pending_information_request = None
        return self._stored_comparison_turn(
            session,
            profile,
            user_text,
            state,
            DialogueAct.COMPARE,
        )

    @staticmethod
    def _focused_wiki_description(
        user_text: str,
        knowledge: GroundedMenuKnowledge,
        fallback: str,
    ) -> tuple[str, str, list[str]]:
        requested_facets = list(routed_knowledge_facets(user_text))
        passages = {passage.facet: passage.content for passage in knowledge.passages}
        supported = {
            "ingredients",
            "safety",
            "preparation",
            "taste",
            "texture",
            "temperature",
            "overview",
        }
        focus = next((facet for facet in requested_facets if facet in supported), "overview")
        detail = passages.get(focus)
        if focus == "ingredients" and not detail:
            detail = "; ".join(
                f"{claim.name_en}: {claim.status.value.lower().replace('_', ' ')}"
                for claim in knowledge.ingredient_claims[:6]
            )
        elif focus == "safety" and not detail:
            detail = "; ".join(
                f"{claim.code}: {claim.status.value.lower().replace('_', ' ')}"
                for claim in knowledge.allergen_claims[:6]
            )
        elif focus == "preparation" and not detail:
            detail = "; ".join(
                claim.value_text for claim in knowledge.preparation_claims[:4]
            )
        return detail or fallback, focus, requested_facets

    @staticmethod
    def _korean_wiki_description(
        focus: str,
        knowledge: GroundedMenuKnowledge,
        user_text: str = "",
    ) -> str:
        if focus == "ingredients":
            items = [
                f"{getattr(claim, 'name_ko', None) or claim.name_en}"
                f"({_CLAIM_STATUS_KO[claim.status.value]})"
                for claim in knowledge.ingredient_claims[:6]
            ]
            if items:
                return "재료 근거: " + ", ".join(items) + "."
        if focus == "safety":
            lowered = user_text.casefold()
            requested_dietary_codes: set[str] = set()
            if "vegan" in lowered or "비건" in lowered:
                requested_dietary_codes = {"contains_animal_product", "vegan_possible"}
            elif "vegetarian" in lowered or "채식" in lowered:
                requested_dietary_codes = {
                    "contains_animal_product",
                    "pork_possible",
                    "vegetarian_possible",
                }
            elif "halal" in lowered or "할랄" in lowered:
                requested_dietary_codes = {
                    "contains_animal_product",
                    "halal_not_verified",
                    "pork_possible",
                }
            dietary_claims = [
                claim
                for claim in knowledge.dietary_claims
                if claim.code.removeprefix("diet_") in _DIETARY_SAFETY_KO
                and (
                    not requested_dietary_codes
                    or claim.code.removeprefix("diet_") in requested_dietary_codes
                )
            ]
            items = [
                f"{_DIETARY_SAFETY_KO[claim.code.removeprefix('diet_')]}"
                f"({_CLAIM_STATUS_KO[claim.status.value]})"
                for claim in dietary_claims
            ]
            present_codes = {
                claim.code.removeprefix("diet_") for claim in dietary_claims
            }
            for missing_code in sorted(requested_dietary_codes - present_codes):
                items.append(f"{_DIETARY_SAFETY_KO[missing_code]}(미확인)")
            if not requested_dietary_codes:
                for claim in knowledge.allergen_claims:
                    status = _CLAIM_STATUS_KO[claim.status.value]
                    if (
                        claim.status.value == "CONFIRMED_ABSENT"
                        and claim.cross_contamination_status == "UNKNOWN"
                    ):
                        status += "·교차 접촉 미확인"
                    items.append(f"{_ALLERGEN_KO.get(claim.code, claim.code)}({status})")
            if items:
                return (
                    "알레르기·식단 위험 근거: "
                    + ", ".join(items)
                    + ". 별도 근거가 없으면 교차 접촉은 미확인으로 유지해요."
                )
        if focus == "preparation":
            methods = list(
                dict.fromkeys(
                    _PREPARATION_KO.get(claim.method, "세부 조리 절차가 가게마다 다른 방식")
                    for claim in knowledge.preparation_claims[:4]
                )
            )
            if methods:
                return (
                    "일반적인 조리법은 "
                    + ", ".join(methods)
                    + "이에요. 가게별 세부 조리법은 다를 수 있어요."
                )
        labels = {
            "taste": "맛",
            "texture": "식감",
            "temperature": "제공 온도",
            "overview": "일반 특징",
        }
        return (
            f"{labels.get(focus, '음식 특징')} 관련 합성 Wiki 근거를 조회했어요. "
            "가게별 레시피와 확인되지 않은 내용은 카드에서 구분해 보여드려요."
        )

    def _snapshot_reference_turn(
        self, session: Session, profile: Profile, user_text: str
    ) -> AssistantTurn | None:
        lowered = user_text.lower()
        compact = lowered.replace(" ", "")
        reference_markers = (
            "first menu",
            "second menu",
            "third menu",
            "1st menu",
            "2nd menu",
            "3rd menu",
            "earlier recommendation",
            "recommended earlier",
            "아까 추천",
            "첫 번째 메뉴",
            "두 번째 메뉴",
            "세 번째 메뉴",
        )
        snapshot = self.repository.get_recommendation_snapshot(session.session_id)
        if snapshot is None or not snapshot.result.candidates:
            return None
        if any(marker in lowered for marker in ("second", "2nd", "두 번째")):
            index = 1
        elif any(marker in lowered for marker in ("third", "3rd", "세 번째")):
            index = 2
        elif any(marker in lowered for marker in ("first", "1st", "첫 번째")):
            index = 0
        else:
            index = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(snapshot.result.candidates)
                    if (
                        (menu := self.repository.get_menu(candidate.menu_id, profile))
                        is not None
                        and (
                            menu.name_en.lower() in lowered
                            or menu.name_ko.replace(" ", "") in compact
                        )
                    )
                ),
                -1,
            )
            if index < 0:
                if not any(marker in lowered for marker in reference_markers):
                    return None
                index = 0
        if index >= len(snapshot.result.candidates):
            return self._make_turn(
                "That earlier recommendation did not contain that many menus. Which visible menu would you like to explore?",
                ChatState.CLARIFICATION,
                [],
                False,
                dialogue_act=DialogueAct.COLLECT_NEEDS,
            )
        candidate = snapshot.result.candidates[index]
        menu = self.repository.get_menu(candidate.menu_id, profile)
        if menu is None:
            return None
        evidence = self.repository.get_evidence(menu.menu_id)
        knowledge = self.repository.get_grounded_menu_knowledge(
            menu.menu_id,
            query=user_text,
            option_item_ids=self._selected_option_ids(menu.menu_id, session.meal_need_state),
        )
        passages_by_facet = {passage.facet: passage.content for passage in knowledge.passages}
        description, requested_facet, requested_facets = self._focused_wiki_description(
            user_text,
            knowledge,
            passages_by_facet.get("overview", menu.description),
        )
        analogy = passages_by_facet.get("analogy", menu.cultural_description)
        unknowns = list(dict.fromkeys([*menu.risk_hints, *knowledge.unknowns]))
        text = f"The {self._ordinal(index + 1)} menu was {menu.name_en}. {description}"
        if requested_facet == "overview":
            text += f" {analogy}"
        if unknowns:
            text += " The restaurant-specific details still marked as unknown are shown below."
        turn = self._make_turn(
            text,
            ChatState.MENU_EXPLANATION,
            [
                Card(
                    type="menu_explanation",
                    title=f"About {menu.name_en}",
                    subtitle="Synthetic menu facts and clearly labelled unknowns",
                    data={
                        "menu": menu.model_dump(mode="json"),
                        "explanation": {
                            "description": description,
                            "requested_facet": requested_facet,
                            "requested_facets": requested_facets,
                            "localized_descriptions": {
                                "한국어": self._korean_wiki_description(
                                    requested_facet,
                                    knowledge,
                                    user_text,
                                )
                            },
                            "cultural_analogy": analogy,
                            "portion": f"Usually serves {menu.serves_min}-{menu.serves_max}",
                            "unknown_fields": unknowns,
                            "evidence_ids": [item.evidence_id for item in evidence],
                            "wiki_passages": [
                                passage.model_dump(mode="json") for passage in knowledge.passages
                            ],
                            "ingredient_claims": [
                                claim.model_dump(mode="json")
                                for claim in knowledge.ingredient_claims
                            ],
                            "allergen_claims": [
                                claim.model_dump(mode="json") for claim in knowledge.allergen_claims
                            ],
                            "dietary_claims": [
                                claim.model_dump(mode="json") for claim in knowledge.dietary_claims
                            ],
                            "preparation_claims": [
                                claim.model_dump(mode="json")
                                for claim in knowledge.preparation_claims
                            ],
                            "merchant_ingredient_claims": [
                                claim.model_dump(mode="json")
                                for claim in knowledge.merchant_ingredient_claims
                            ],
                            "grounded_claim_ids": knowledge.claim_ids,
                            "grounded_passage_ids": [
                                passage.chunk_id for passage in knowledge.passages
                            ],
                            "source_snapshot_id": snapshot.snapshot_id,
                            "source_position": index + 1,
                        },
                    },
                )
            ],
            False,
            [],
            dialogue_act=DialogueAct.EXPLAIN,
        )
        language = self._narrative_language(profile.preferred_language)
        if language != "English":
            ui_copy = _INFORMATION_UI_COPY[language]
            turn.cards[0].title = str(ui_copy["explanation_title"]).format(
                category=menu.name_ko if language == "한국어" else menu.name_en
            )
            turn.cards[0].subtitle = str(ui_copy["explanation_subtitle"])
            turn.text = self._server_grounded_text(turn, profile.preferred_language)
        return turn

    def _generic_explanation_turn(
        self,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        if requested_act != DialogueAct.REQUEST_EXPLANATION:
            return None
        category = self._catalog_category(user_text)
        if category is None:
            return None
        comparisons = self.repository.compare_merchants(
            category,
            profile,
            limit=1,
            meal_need_state=state,
        )
        compatible_listing = bool(comparisons)
        source_menu_id = (
            comparisons[0].menu_id
            if comparisons
            else self.repository.get_category_knowledge_source(category)
        )
        if source_menu_id is None:
            language = self._narrative_language(profile.preferred_language)
            return self._make_turn(
                _NO_EXPLANATION_LISTING_COPY[language],
                ChatState.CLARIFICATION,
                [],
                False,
                dialogue_act=DialogueAct.EXPLAIN,
            )
        menu = self.repository.get_menu(source_menu_id, profile)
        if menu is None:
            return None
        knowledge = self.repository.get_grounded_menu_knowledge(
            menu.menu_id,
            query=user_text,
            option_item_ids=self._selected_option_ids(menu.menu_id, state),
        )
        passages_by_facet = {passage.facet: passage.content for passage in knowledge.passages}
        overview = passages_by_facet.get("overview", menu.description)
        taste = passages_by_facet.get("taste")
        texture = passages_by_facet.get("texture")
        analogy = passages_by_facet.get("analogy", menu.cultural_description)
        description, requested_facet, requested_facets = self._focused_wiki_description(
            user_text,
            knowledge,
            overview,
        )
        narrative = (
            " ".join(part for part in (overview, taste, texture, analogy) if part)
            if requested_facet == "overview"
            else description
        )
        narrative += (
            " This is general synthetic Wiki knowledge, not proof of one restaurant's exact "
            "recipe, certification, or cross-contact safety."
        )
        source_ids = list(
            dict.fromkeys(
                [
                    *knowledge.claim_ids,
                    *[passage.chunk_id for passage in knowledge.passages],
                ]
            )
        )
        explanation = {
            "description": description,
            "requested_facet": requested_facet,
            "requested_facets": requested_facets,
            "localized_descriptions": {
                "한국어": self._korean_wiki_description(
                    requested_facet,
                    knowledge,
                    user_text,
                )
            },
            "cultural_analogy": analogy,
            "portion": f"Usually serves {menu.serves_min}-{menu.serves_max}",
            "unknown_fields": knowledge.unknowns,
            "evidence_ids": source_ids,
            "wiki_passages": [passage.model_dump(mode="json") for passage in knowledge.passages],
            "ingredient_claims": [
                claim.model_dump(mode="json") for claim in knowledge.ingredient_claims
            ],
            "allergen_claims": [
                claim.model_dump(mode="json") for claim in knowledge.allergen_claims
            ],
            "dietary_claims": [
                claim.model_dump(mode="json") for claim in knowledge.dietary_claims
            ],
            "preparation_claims": [
                claim.model_dump(mode="json") for claim in knowledge.preparation_claims
            ],
            "merchant_ingredient_claims": [
                claim.model_dump(mode="json")
                for claim in knowledge.merchant_ingredient_claims
            ],
            "grounded_claim_ids": knowledge.claim_ids,
            "grounded_passage_ids": [passage.chunk_id for passage in knowledge.passages],
            "concept_id": knowledge.concept_id,
            "concept_lineage": knowledge.concept_lineage,
            "general_wiki_explanation": True,
            "category": category,
            "compatible_listing": compatible_listing,
            "is_synthetic": True,
        }
        card_data: dict[str, Any] = {"explanation": explanation}
        if compatible_listing:
            card_data["menu"] = menu.model_dump(mode="json")
        turn = self._make_turn(
            narrative,
            ChatState.MENU_EXPLANATION,
            [
                Card(
                    type="menu_explanation",
                    title=f"What {category} is like",
                    subtitle=(
                        "General synthetic dish Wiki · representative demo listing"
                        if compatible_listing
                        else "General synthetic dish Wiki · no compatible listing shown"
                    ),
                    data=card_data,
                )
            ],
            False,
            ["Recommend this food when ready", "Ask about ingredients", "Explain another dish"],
            dialogue_act=DialogueAct.EXPLAIN,
        )
        language = self._narrative_language(profile.preferred_language)
        ui_copy = _INFORMATION_UI_COPY[language]
        turn.cards[0].title = str(ui_copy["explanation_title"]).format(category=category)
        turn.cards[0].subtitle = str(
            ui_copy[
                "explanation_subtitle"
                if compatible_listing
                else "explanation_no_listing_subtitle"
            ]
        )
        turn.suggested_replies = list(ui_copy["explanation_replies"])
        if not compatible_listing:
            turn.suggested_replies = turn.suggested_replies[1:]
        if language == "English":
            turn.suggested_replies[:2] = (
                [f"Recommend {category}", f"Explain {category} ingredients"]
                if compatible_listing
                else [f"Explain {category} ingredients", "Explain another dish"]
            )
        elif language == "한국어":
            turn.suggested_replies[:2] = (
                [f"{category} 추천", f"{category} 재료 설명"]
                if compatible_listing
                else [f"{category} 재료 설명", "다른 음식 설명"]
            )
        elif language == "日本語":
            turn.suggested_replies[:2] = (
                [
                    f"この料理をおすすめして (Recommend {category})",
                    f"材料を確認 (Explain {category} ingredients)",
                ]
                if compatible_listing
                else [
                    f"材料を確認 (Explain {category} ingredients)",
                    "別の料理を説明 (Explain another dish)",
                ]
            )
        else:
            turn.suggested_replies[:2] = (
                [
                    f"Recomienda esta comida (Recommend {category})",
                    f"Preguntar por ingredientes (Explain {category} ingredients)",
                ]
                if compatible_listing
                else [
                    f"Preguntar por ingredientes (Explain {category} ingredients)",
                    "Explicar otro plato (Explain another dish)",
                ]
            )
        if language != "English":
            turn.text = self._server_grounded_text(turn, profile.preferred_language)
        return turn

    @staticmethod
    def _catalog_category(user_text: str) -> str | None:
        lowered = " ".join(user_text.lower().split())
        compact = lowered.replace(" ", "")
        aliases = {
            "kimbap": "Gimbap",
            "jajangmyeon": "Jjajangmyeon",
            "soft tofu stew": "Sundubu",
            "fish cake": "Eomuk",
            "korean dumpling": "Mandu",
            "lunch box": "Dosirak",
        }
        category = next(
            (
                name_en
                for name_en, name_ko, _, _ in sorted(
                    CATEGORIES,
                    key=lambda item: max(len(item[0]), len(item[1])),
                    reverse=True,
                )
                if name_en.lower() in lowered or name_ko.replace(" ", "") in compact
            ),
            None,
        )
        if category is not None:
            return category
        return next(
            (canonical for alias, canonical in aliases.items() if alias in lowered),
            None,
        )

    def _target_clarification_turn(
        self,
        profile: Profile,
        requested_act: DialogueAct,
        state: MealNeedState,
    ) -> AssistantTurn:
        language = self._narrative_language(profile.preferred_language)
        key: Literal["compare", "explain"] = (
            "compare" if requested_act == DialogueAct.COMPARE else "explain"
        )
        state.pending_information_request = key
        text = _TARGET_CLARIFICATION_COPY[language][key]
        if language in _INPUT_LANGUAGE_NOTICE:
            text += _INPUT_LANGUAGE_NOTICE[language]
        return self._make_turn(
            text,
            ChatState.CLARIFICATION,
            [],
            False,
            dialogue_act=DialogueAct.COLLECT_NEEDS,
        )

    def _pending_information_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        pending = state.pending_information_request
        if pending is None or requested_act != DialogueAct.COLLECT_NEEDS:
            return None
        if pending == "explain":
            snapshot_turn = self._snapshot_reference_turn(session, profile, user_text)
            if snapshot_turn is not None:
                if snapshot_turn.dialogue_act == DialogueAct.EXPLAIN:
                    state.pending_information_request = None
                return snapshot_turn
        else:
            snapshot_turn = self._natural_snapshot_comparison_turn(
                session,
                profile,
                user_text,
                state,
                DialogueAct.COMPARE,
            )
            if snapshot_turn is not None:
                if snapshot_turn.cards:
                    state.pending_information_request = None
                return snapshot_turn
        category = self._catalog_category(user_text)
        if category is None:
            source_act = (
                DialogueAct.COMPARE
                if pending == "compare"
                else DialogueAct.REQUEST_EXPLANATION
            )
            return self._target_clarification_turn(profile, source_act, state)
        state.pending_information_request = None
        if pending == "explain":
            return self._generic_explanation_turn(
                profile,
                user_text,
                state,
                DialogueAct.REQUEST_EXPLANATION,
            )
        return self._category_comparison_turn(
            profile,
            user_text,
            state,
            DialogueAct.COMPARE,
        )

    def _category_comparison_turn(
        self,
        profile: Profile,
        user_text: str,
        state: MealNeedState,
        requested_act: DialogueAct,
    ) -> AssistantTurn | None:
        if requested_act != DialogueAct.COMPARE:
            return None
        category = self._catalog_category(user_text)
        if category is None:
            return None
        comparisons = self.repository.compare_merchants(
            category,
            profile,
            meal_need_state=state,
        )
        if not comparisons:
            language = self._narrative_language(profile.preferred_language)
            return self._make_turn(
                _NO_COMPARISON_COPY[language],
                ChatState.CLARIFICATION,
                [],
                False,
                dialogue_act=DialogueAct.COMPARE,
            )
        turn = self._make_turn(
            f"Here are the grounded restaurant trade-offs for {category}. Prices, "
            "delivery details, and unresolved dietary information remain visible.",
            ChatState.MERCHANT_COMPARISON,
            [
                Card(
                    type="merchant_comparison",
                    title=f"{category} comparison",
                    subtitle="Synthetic restaurants · shared comparison axes",
                    data={
                        "merchants": [item.model_dump(mode="json") for item in comparisons]
                    },
                )
            ],
            False,
            ["Explain the first option", "Show another food direction"],
            dialogue_act=DialogueAct.COMPARE,
        )
        language = self._narrative_language(profile.preferred_language)
        ui_copy = _INFORMATION_UI_COPY[language]
        turn.cards[0].title = str(ui_copy["comparison_title"]).format(category=category)
        turn.cards[0].subtitle = str(ui_copy["comparison_subtitle"])
        turn.suggested_replies = list(ui_copy["comparison_replies"])
        if language == "English":
            turn.suggested_replies[0] = f"Explain {category}"
        elif language == "한국어":
            turn.suggested_replies[0] = f"{category} 설명"
        elif language == "日本語":
            turn.suggested_replies[0] = f"この料理を説明 (Explain {category})"
        else:
            turn.suggested_replies[0] = f"Explicar esta comida (Explain {category})"
        if language != "English":
            turn.text = self._server_grounded_text(turn, profile.preferred_language)
        return turn

    @staticmethod
    def _ordinal(value: int) -> str:
        return {1: "first", 2: "second", 3: "third"}.get(value, f"number {value}")

    @staticmethod
    def _classify_fallback(exc: Exception | None) -> FallbackReason:
        if exc is None:
            return FallbackReason.PROVIDER_UNAVAILABLE
        message = str(exc).upper()
        name = type(exc).__name__.upper()
        if "RATE" in message and "LIMIT" in message:
            return FallbackReason.RATE_LIMIT
        if "TIMEOUT" in message or "TIMEOUT" in name:
            return FallbackReason.TIMEOUT
        if any(marker in message or marker in name for marker in ("CONNECT", "NETWORK")):
            return FallbackReason.NETWORK_ERROR
        if "INVALID_TOOL" in message or "VALIDATION" in name:
            return FallbackReason.INVALID_TOOL_ARGUMENT
        if "NO_TOOL_RESPONSE" in message:
            return FallbackReason.NO_TOOL_RESPONSE
        if "EMPTY_RESPONSE" in message:
            return FallbackReason.EMPTY_RESPONSE
        if "GROUNDING" in message:
            return FallbackReason.GROUNDING_REJECTED
        if "CAPABILITY_LIMIT_EXCEEDED" in message:
            return FallbackReason.PROVIDER_UNAVAILABLE
        if "NO_MODEL" in message or "UNAVAILABLE" in message:
            return FallbackReason.PROVIDER_UNAVAILABLE
        return FallbackReason.UNKNOWN_PROVIDER_ERROR

    @staticmethod
    def _narrative_language(preferred_language: str) -> str:
        normalized = _CHAT_LANGUAGE_ALIASES.get(preferred_language.strip().lower())
        if normalized in _SERVER_NARRATIVE_LANGUAGES:
            return normalized
        return "English"

    @classmethod
    def _server_grounded_text(
        cls,
        turn: AssistantTurn,
        preferred_language: str = "English",
    ) -> str:
        # A single agent turn can read options and then mutate the cart, or read the
        # cart and then create/complete checkout. Render the final authoritative
        # outcome, regardless of the order in which cards arrived from the provider.
        language = cls._narrative_language(preferred_language)
        copy = _GROUNDED_COPY[language]
        menu_name_key = "name_ko" if language == "한국어" else "name_en"
        priority = {
            "order_complete": 0,
            "payment_cta": 1,
            "cart_summary": 2,
            "address_confirmation": 3,
            "translated_note": 4,
            "option_question": 5,
            "dietary_evidence": 6,
            "merchant_comparison": 7,
            "menu_explanation": 8,
            "menu_recommendations": 9,
            "category_recommendations": 10,
            "preset_collection": 11,
        }
        ordered_cards = sorted(
            turn.cards,
            key=lambda card: priority.get(card.type, len(priority)),
        )
        for card in ordered_cards:
            if card.type == "menu_recommendations":
                menus = card.data.get("menus")
                if isinstance(menus, list):
                    names = [
                        str(menu.get(menu_name_key))
                        for menu in menus[:3]
                        if isinstance(menu, dict) and menu.get(menu_name_key)
                    ]
                    if names:
                        return copy["menus"].format(names=", ".join(names))
            if card.type == "category_recommendations":
                categories = card.data.get("categories")
                if isinstance(categories, list):
                    names = [
                        str(item.get("category"))
                        for item in categories[:4]
                        if isinstance(item, dict) and item.get("category")
                    ]
                    if names:
                        return copy["categories"].format(names=", ".join(names))
            if card.type == "menu_explanation":
                menu = card.data.get("menu")
                explanation = card.data.get("explanation")
                if isinstance(menu, dict):
                    name = menu.get(menu_name_key)
                    description = menu.get("description")
                    if isinstance(explanation, dict):
                        localized_descriptions = explanation.get("localized_descriptions")
                        explanation_description = (
                            localized_descriptions.get(language)
                            if language != "English" and isinstance(localized_descriptions, dict)
                            else explanation.get("description")
                        )
                        if language == "한국어" and not explanation_description:
                            explanation_description = (
                                "조회한 합성 Wiki 근거를 카드에 표시했어요. "
                                "가게별 미확인 정보는 안전하다고 보지 않아요."
                            )
                        if explanation_description:
                            description = explanation_description
                        passages = explanation.get("wiki_passages")
                        if not explanation_description and isinstance(passages, list):
                            overview = next(
                                (
                                    passage.get("content")
                                    for passage in passages
                                    if isinstance(passage, dict)
                                    and passage.get("facet") == "overview"
                                ),
                                None,
                            )
                            description = overview or description
                    if name and description:
                        return copy["explanation"].format(
                            name=name,
                            description=description,
                        )
                if isinstance(explanation, dict):
                    name = explanation.get("category")
                    localized_descriptions = explanation.get("localized_descriptions")
                    description = (
                        localized_descriptions.get(language)
                        if language != "English" and isinstance(localized_descriptions, dict)
                        else explanation.get("description")
                    )
                    if language == "한국어" and not description:
                        description = (
                            "조회한 합성 Wiki 근거를 카드에 표시했어요. "
                            "가게별 미확인 정보는 안전하다고 보지 않아요."
                        )
                    if not description:
                        passages = explanation.get("wiki_passages")
                        description = (
                            next(
                                (
                                    passage.get("content")
                                    for passage in passages
                                    if isinstance(passage, dict)
                                    and passage.get("facet") == "overview"
                                ),
                                None,
                            )
                            if isinstance(passages, list)
                            else None
                        )
                    if name and description:
                        return copy["explanation"].format(
                            name=name,
                            description=description,
                        )
            if card.type == "merchant_comparison":
                return copy["comparison"]
            if card.type == "dietary_evidence":
                return copy["dietary"]
            if card.type == "option_question":
                groups = card.data.get("option_groups")
                names = (
                    [
                        str(group.get("name_en"))
                        for group in groups
                        if isinstance(group, dict) and group.get("name_en")
                    ]
                    if isinstance(groups, list)
                    else []
                )
                detail = ", ".join(names[:4]) or "the required menu options"
                return copy["options"].format(detail=detail)
            if card.type == "translated_note":
                return copy["note"]
            if card.type == "address_confirmation":
                candidates = card.data.get("candidates")
                count = len(candidates) if isinstance(candidates, list) else 0
                return copy["address"].format(
                    count=count,
                    matches="matches" if count != 1 else "match",
                )
            if card.type == "cart_summary":
                cart = card.data.get("cart")
                if isinstance(cart, dict):
                    items = cart.get("items")
                    item_count = len(items) if isinstance(items, list) else 0
                    total = cart.get("total_price")
                    missing = cart.get("missing_slots")
                    missing_count = len(missing) if isinstance(missing, list) else 0
                    total_text = f"₩{int(total):,}" if isinstance(total, int) else "the shown total"
                    return copy["cart"].format(
                        item_count=item_count,
                        items="items" if item_count != 1 else "item",
                        total=total_text,
                        missing_count=missing_count,
                        fields=("fields remain" if missing_count != 1 else "field remains"),
                    )
            if card.type == "payment_cta":
                checkout = card.data.get("checkout")
                if isinstance(checkout, dict):
                    checkout_status = str(checkout.get("status") or "PENDING")
                    amount = checkout.get("amount")
                    amount_text = (
                        f"₩{int(amount):,}" if isinstance(amount, int) else "the displayed amount"
                    )
                    return copy["payment"].format(
                        status=checkout_status,
                        amount=amount_text,
                    )
            if card.type == "order_complete":
                order = card.data.get("order")
                if isinstance(order, dict):
                    order_status = str(order.get("order_status") or "CONFIRMED")
                    return copy["order"].format(status=order_status)
            if card.type == "preset_collection":
                return copy["preset"]
        return turn.text

    def _needs_collection_turn(
        self,
        profile: Profile,
        user_act: DialogueAct,
        readiness: ReadinessDecision,
    ) -> AssistantTurn:
        language = self._narrative_language(profile.preferred_language)
        copy = _NEEDS_COPY[language]
        if user_act == DialogueAct.GREET:
            text = str(copy["greet"])
            replies = list(copy["greet_replies"])
            act = DialogueAct.GREET
        elif readiness.status.value == "HELD":
            text = str(copy["held"])
            replies = list(copy["held_replies"])
            act = DialogueAct.HOLD_RECOMMENDATION
        else:
            question_key = readiness.next_question_key or "meal_direction"
            text = str(copy.get(question_key, copy["meal_direction"]))
            replies = []
            act = DialogueAct.COLLECT_NEEDS
        if language in _INPUT_LANGUAGE_NOTICE:
            text += _INPUT_LANGUAGE_NOTICE[language]
        elif (
            profile.preferred_language not in {"English", "한국어", "Korean"}
            and language == "English"
        ):
            text += (
                f" The guided interface is set to {profile.preferred_language}, but this "
                "deterministic chat path currently recognises meal needs in English and "
                "Korean. Please enter your meal needs in one of those languages."
            )
        if profile.preferred_language.lower() == "korean":
            if user_act == DialogueAct.GREET:
                text = "안녕하세요! 바로 메뉴를 보여드리기 전에 취향을 먼저 알아볼게요. 따뜻하고 든든한 음식과 가볍고 산뜻한 음식 중 어느 쪽이 끌리세요?"
            elif readiness.status.value == "HELD":
                text = "알겠어요. 메뉴 추천은 잠시 보류하고 한 번에 하나씩 여쭤볼게요. 오늘은 어떤 맛이나 느낌의 음식이 좋으세요?"
        return self._make_turn(
            text,
            ChatState.DISCOVERY if act == DialogueAct.GREET else ChatState.CLARIFICATION,
            [],
            False,
            replies,
            dialogue_act=act,
            readiness=readiness,
        )

    def _preset_turn(
        self,
        session: Session,
        profile: Profile,
        intent: Literal["weekly_ranking", "kpop_demon_hunters"],
        meal_need_state: MealNeedState,
    ) -> AssistantTurn:
        if intent == "weekly_ranking":
            definitions = [
                (1, "BBQ", "Crisp Korean fried chicken", "menu_021_01"),
                (2, "BHC", "Sweet-savoury seasoned chicken", "menu_022_01"),
                (3, "No More Pizza", "A shareable half-and-half pizza", "menu_023_01"),
                (4, "Hong Kong Banjeom", "Korean-Chinese noodles and tangsuyuk", "menu_024_01"),
                (5, "Yeopgi Tteokbokki", "Bold chewy tteokbokki", "menu_025_01"),
            ]
            title = "This week's delivery ranking"
            text = "Here is this week's fixed YOBI delivery ranking. Swipe through a nearby menu from every ranked restaurant."
            subtitle = "Five popular delivery picks"
        else:
            definitions = [
                (1, "Gimbap", "Colourful rice rolls wrapped in seaweed", "menu_026_01"),
                (2, "Gukbap", "A warming Korean soup-and-rice meal", "menu_027_01"),
                (3, "Hotteok", "A crisp, chewy filled street pancake", "menu_028_01"),
                (4, "Seolleongtang", "A mild slow-simmered beef-bone soup", "menu_029_01"),
                (5, "Eomuk", "Springy fish cake with warm broth", "menu_030_01"),
            ]
            title = "K-POP Demon Hunters food guide"
            text = "Meet five Korean foods featured in the K-POP Demon Hunters menu. Swipe to explore a nearby delivery pick for each one."
            subtitle = "Five foods to explore"
        entries: list[dict[str, object]] = []
        for rank, label, description, menu_id in definitions:
            if not self._menu_still_satisfies_active_constraints(
                menu_id, profile, meal_need_state
            ):
                continue
            menu = self.repository.get_menu(menu_id, profile)
            if menu is None:
                raise RuntimeError("PRESET_MENU_MISSING")
            entries.append(
                {
                    "rank": rank,
                    "label": label,
                    "description": description,
                    "menu": menu.model_dump(mode="json"),
                }
            )
        if not entries:
            return self._make_turn(
                "None of this preset collection satisfies every active dietary, allergy, "
                "delivery-area, and meal constraint, so I will not show it as orderable. "
                "Would you like a fresh recommendation using those constraints?",
                ChatState.CLARIFICATION,
                [],
                False,
                ["Recommend a safe alternative", "Review my constraints"],
                dialogue_act=DialogueAct.COLLECT_NEEDS,
            )
        if len(entries) != len(definitions):
            text += " Items that conflicted with your active constraints were omitted."
        return self._make_turn(
            text,
            ChatState.MENU_EXPLANATION,
            [
                Card(
                    type="preset_collection",
                    title=title,
                    subtitle=subtitle,
                    data={"kind": intent, "entries": entries},
                )
            ],
            False,
        )

    def _dynamic_context(
        self,
        session: Session,
        profile: Profile,
        meal_need_state: MealNeedState | None = None,
        readiness: ReadinessDecision | None = None,
        current_dialogue_act: DialogueAct | None = None,
    ) -> str:
        cart = self.repository.get_cart(session.session_id)
        recent_messages = self.repository.list_messages(session.session_id)[-5:]
        context = {
            "state": session.state.value,
            "language": profile.preferred_language,
            "dietary_rules": profile.dietary_rules,
            "allergy_severity": profile.allergy_severity,
            "spice_tolerance": profile.spice_tolerance,
            "favorite_foods": profile.favorite_foods,
            "selected_menu_id": session.selected_menu_id,
            "selected_merchant_id": session.selected_merchant_id,
            "dialogue_act": (
                current_dialogue_act.value
                if current_dialogue_act is not None
                else session.dialogue_act.value
            ),
            "previous_dialogue_act": session.dialogue_act.value,
            "meal_need_state": (meal_need_state or session.meal_need_state).model_dump(mode="json"),
            "recommendation_readiness": readiness.model_dump(mode="json") if readiness else None,
            "cart": {
                "item_count": len(cart.items),
                "total_price_krw": cart.total_price,
                "missing_requirements": cart.missing_slots,
                "ready_to_checkout": cart.ready_to_checkout,
            },
            "recent_messages": [
                {"role": message["role"], "content": message["content"][:500]}
                for message in recent_messages
            ],
        }
        return json.dumps(context, ensure_ascii=False, separators=(",", ":"))

    def _turn_from_tool_results(
        self,
        session: Session,
        text: str,
        tool_results: list[tuple[str, dict[str, object]]],
        requested_act: DialogueAct = DialogueAct.REQUEST_RECOMMENDATION,
        source_query: str | None = None,
    ) -> AssistantTurn:
        cards: list[Card] = []
        state = session.state
        rendered_tools: set[str] = set()
        for name, result in tool_results:
            if name in rendered_tools:
                continue
            card_count = len(cards)
            if name == "recommend_menu_categories":
                categories = self._merge_tool_items(tool_results, name, "categories", "category")
                if not categories:
                    continue
                cards.append(
                    Card(
                        type="category_recommendations",
                        title="Korean food directions that fit",
                        subtitle="Grounded in the synthetic menu catalog",
                        data={"categories": categories},
                    )
                )
                state = ChatState.CATEGORY_SHORTLIST
            elif name == "search_menus":
                menus = self._merge_tool_items(tool_results, name, "menus", "menu_id")
                if not menus:
                    continue
                cards.append(
                    Card(
                        type="menu_recommendations",
                        title="Grounded menu matches",
                        subtitle="Synthetic catalog · prices and evidence checked server-side",
                        data={"menus": menus},
                    )
                )
                state = ChatState.MENU_EXPLANATION
            elif name == "explain_menu" and result.get("menu"):
                menu_payload = result["menu"]
                explanation_payload = result.get("explanation")
                if not isinstance(menu_payload, dict) or not isinstance(
                    explanation_payload, dict
                ):
                    continue
                explanation = dict(explanation_payload)
                knowledge = GroundedMenuKnowledge.model_validate(
                    {
                        "menu_id": str(menu_payload["menu_id"]),
                        "ingredient_claims": explanation.get("ingredient_claims", []),
                        "allergen_claims": explanation.get("allergen_claims", []),
                        "dietary_claims": explanation.get("dietary_claims", []),
                        "preparation_claims": explanation.get("preparation_claims", []),
                        "merchant_ingredient_claims": explanation.get(
                            "merchant_ingredient_claims", []
                        ),
                        "passages": explanation.get("wiki_passages", []),
                        "unknowns": explanation.get("unknown_fields", []),
                    }
                )
                description, requested_facet, requested_facets = (
                    self._focused_wiki_description(
                        source_query or "",
                        knowledge,
                        str(explanation.get("description") or menu_payload.get("description") or ""),
                    )
                )
                explanation.update(
                    {
                        "description": description,
                        "requested_facet": requested_facet,
                        "requested_facets": requested_facets,
                        "localized_descriptions": {
                            "한국어": self._korean_wiki_description(
                                requested_facet,
                                knowledge,
                                source_query or "",
                            )
                        },
                    }
                )
                cards.append(
                    Card(
                        type="menu_explanation",
                        title="What this dish will feel like",
                        subtitle="Taste, texture, portion, and unknowns",
                        data={"menu": menu_payload, "explanation": explanation},
                    )
                )
                state = ChatState.MENU_EXPLANATION
            elif name == "get_dietary_evidence":
                evidence = self._merge_tool_items(tool_results, name, "evidence", "evidence_id")
                ingredient_claims = self._merge_tool_items(
                    tool_results, name, "ingredient_claims", "source_id", limit=None
                )
                allergen_claims = self._merge_tool_items(
                    tool_results, name, "allergen_claims", "source_id", limit=None
                )
                dietary_claims = self._merge_tool_items(
                    tool_results, name, "dietary_claims", "source_id", limit=None
                )
                preparation_claims = self._merge_tool_items(
                    tool_results, name, "preparation_claims", "source_id", limit=None
                )
                merchant_claims = self._merge_tool_items(
                    tool_results, name, "merchant_ingredient_claims", "source_id", limit=None
                )
                wiki_passages = self._merge_tool_items(
                    tool_results, name, "wiki_passages", "chunk_id", limit=None
                )
                menu_ids: list[str] = []
                unknown_fields: list[str] = []
                grounded_claim_ids: list[str] = []
                grounded_passage_ids: list[str] = []
                for tool_name, dietary_result in tool_results:
                    if tool_name != name:
                        continue
                    menu_id = dietary_result.get("menu_id")
                    if menu_id and str(menu_id) not in menu_ids:
                        menu_ids.append(str(menu_id))
                    for source_key, target in (
                        ("unknown_fields", unknown_fields),
                        ("grounded_claim_ids", grounded_claim_ids),
                        ("grounded_passage_ids", grounded_passage_ids),
                    ):
                        values = dietary_result.get(source_key)
                        if not isinstance(values, list):
                            continue
                        for value in values:
                            normalized = str(value)
                            if normalized not in target:
                                target.append(normalized)
                if not any(
                    (
                        evidence,
                        ingredient_claims,
                        allergen_claims,
                        dietary_claims,
                        preparation_claims,
                        wiki_passages,
                    )
                ):
                    continue
                cards.append(
                    Card(
                        type="dietary_evidence",
                        title="Dietary evidence",
                        subtitle="Evidence status is not a safety guarantee",
                        data={
                            "menus": [{"menu_id": menu_id} for menu_id in menu_ids],
                            "evidence": evidence,
                            "ingredient_claims": ingredient_claims,
                            "allergen_claims": allergen_claims,
                            "dietary_claims": dietary_claims,
                            "preparation_claims": preparation_claims,
                            "merchant_ingredient_claims": merchant_claims,
                            "wiki_passages": wiki_passages,
                            "unknown_fields": unknown_fields,
                            "grounded_claim_ids": grounded_claim_ids,
                            "grounded_passage_ids": grounded_passage_ids,
                        },
                    )
                )
                state = ChatState.SAFETY_WARNING
            elif name == "compare_merchants":
                merchants = self._merge_tool_items(tool_results, name, "merchants", "merchant_id")
                if not merchants:
                    continue
                cards.append(
                    Card(
                        type="merchant_comparison",
                        title="Compare the trade-offs",
                        subtitle="Same axes · synthetic demo restaurants",
                        data={"merchants": merchants},
                    )
                )
                state = ChatState.MERCHANT_COMPARISON
            elif name == "get_menu_options":
                option_groups = self._merge_tool_items(
                    tool_results, name, "option_groups", "option_group_id"
                )
                if not option_groups:
                    continue
                cards.append(
                    Card(
                        type="option_question",
                        title="Choose one option at a time",
                        data={"option_groups": option_groups},
                    )
                )
                state = ChatState.MENU_OPTIONS
            elif name == "translate_order_note" and result.get("korean_translation"):
                cards.append(
                    Card(
                        type="translated_note",
                        title="Review the translated note",
                        subtitle="Confirmation required before sending",
                        data=result,
                    )
                )
            elif name == "resolve_address" and result.get("candidates"):
                cards.append(
                    Card(
                        type="address_confirmation",
                        title="Confirm the delivery address",
                        subtitle="YOBI never confirms OCR output automatically",
                        data=result,
                    )
                )
                state = ChatState.DELIVERY_ADDRESS
            elif name == "get_cart_preview" and result.get("cart"):
                cards.append(
                    Card(
                        type="cart_summary",
                        title="Server-calculated cart",
                        subtitle="Prices and required slots rechecked",
                        data=result,
                    )
                )
                state = ChatState.ORDER_REVIEW
            elif name in {"update_cart", "update_delivery_preferences"} and result.get("cart"):
                cards.append(
                    Card(
                        type="cart_summary",
                        title="Server-calculated demo cart",
                        subtitle="The explicit change was saved and all prices were rechecked",
                        data=result,
                    )
                )
                state = (
                    ChatState.DELIVERY_OPTIONS
                    if name == "update_delivery_preferences"
                    else ChatState.ORDER_REVIEW
                )
            elif name in {"create_mock_checkout", "get_mock_payment_status"} and result.get(
                "checkout"
            ):
                checkout = result.get("checkout")
                cards.append(
                    Card(
                        type="payment_cta",
                        title="Mock payment",
                        subtitle="Demo only · no real charge or restaurant order",
                        data=result,
                    )
                )
                status = checkout.get("status") if isinstance(checkout, dict) else None
                state = (
                    ChatState.PAYMENT_COMPLETE
                    if status == "SUCCEEDED"
                    else ChatState.PAYMENT_PENDING
                )
            elif name == "complete_mock_order" and result.get("order"):
                cards.append(
                    Card(
                        type="order_complete",
                        title="Mock order complete",
                        subtitle="Synthetic order · no restaurant received it",
                        data=result,
                    )
                )
                state = ChatState.ORDER_COMPLETE
            if len(cards) > card_count:
                rendered_tools.add(name)
        output_act = {
            DialogueAct.REQUEST_EXPLANATION: DialogueAct.EXPLAIN,
            DialogueAct.COMPARE: DialogueAct.COMPARE,
            DialogueAct.SELECT: DialogueAct.SELECT,
            DialogueAct.ORDER_ACTION: DialogueAct.ORDER_ACTION,
        }.get(requested_act, DialogueAct.RECOMMEND)
        suggested_replies: list[str] = []
        if output_act == DialogueAct.RECOMMEND:
            if any(card.type == "menu_recommendations" for card in cards):
                suggested_replies = ["Compare these", "Something else", "Show dietary evidence"]
            else:
                category_card = next(
                    (card for card in cards if card.type == "category_recommendations"),
                    None,
                )
                category_items = category_card.data.get("categories") if category_card else None
                if isinstance(category_items, list):
                    suggested_replies = [
                        f"Recommend {item['category']}"
                        for item in category_items[:3]
                        if isinstance(item, dict) and item.get("category")
                    ]
        return self._make_turn(
            text,
            state,
            cards,
            False,
            suggested_replies,
            dialogue_act=output_act,
        )

    @staticmethod
    def _merge_tool_items(
        tool_results: list[tuple[str, dict[str, object]]],
        tool_name: str,
        list_key: str,
        identity_key: str,
        *,
        limit: int | None = 12,
    ) -> list[dict[str, object]]:
        merged: list[dict[str, object]] = []
        seen: set[str] = set()
        for name, result in tool_results:
            if name != tool_name:
                continue
            items = result.get(list_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = {str(key): value for key, value in item.items()}
                identity_value = normalized.get(identity_key)
                identity = (
                    str(identity_value)
                    if identity_value is not None
                    else json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)
                )
                if identity in seen:
                    continue
                seen.add(identity)
                merged.append(normalized)
                if limit is not None and len(merged) == limit:
                    return merged
        return merged

    def _deterministic_turn(
        self,
        session: Session,
        profile: Profile,
        user_text: str,
        meal_need_state: MealNeedState | None = None,
    ) -> AssistantTurn:
        lowered = user_text.lower()
        active_needs = meal_need_state or session.meal_need_state
        if any(phrase in lowered for phrase in ("walking in the rain", "warm and mild", "rainy")):
            menus = self.repository.recommend_menus(user_text, profile, active_needs, limit=12)
            categories: list[dict[str, object]] = []
            for menu in menus:
                if any(item["category"] == menu.category for item in categories):
                    continue
                categories.append(
                    {
                        "category": menu.category,
                        "description": menu.cultural_description,
                        "match_reasons": menu.match_reasons,
                        "risk_hints": menu.risk_hints,
                        "source_ids": [menu.menu_id, menu.merchant_id, *menu.evidence_ids],
                    }
                )
                if len(categories) == 4:
                    break
            if not categories:
                return self._make_turn(
                    "I could not find an available menu that satisfies every current hard "
                    "constraint. Which one may be flexible: budget, spice level, food type, "
                    "or delivery area?",
                    ChatState.CLARIFICATION,
                    [],
                    False,
                    ["Keep every constraint", "Adjust my budget", "Try another food type"],
                    dialogue_act=DialogueAct.COLLECT_NEEDS,
                )
            first_category = str(categories[0]["category"])
            applied_needs = self._need_summary(active_needs, "no additional structured constraints")
            badges = self._active_need_badges(active_needs)
            return self._make_turn(
                f"Using only the meal needs currently saved, the strongest available direction "
                f"is {first_category}. The active needs are: {applied_needs}.",
                ChatState.CATEGORY_SHORTLIST,
                [
                    Card(
                        type="category_recommendations",
                        title="Directions for your current needs",
                        subtitle=(
                            " · ".join(badges) if badges else "No additional hard constraints saved"
                        ),
                        data={"categories": categories},
                    )
                ],
                False,
                [
                    *[f"Recommend {item['category']}" for item in categories[:3]],
                    "Try another food type",
                ],
            )

        if "vegan" in lowered:
            vegan = self.repository.get_menu("menu_004_01", profile)
            assert vegan
            active_allergies = [
                rule.removesuffix("_allergy").replace("_", " ")
                for rule in active_needs.dietary_rules
                if rule.endswith("_allergy")
            ]
            severe_allergy = bool(active_allergies) and profile.allergy_severity == "severe"
            allergy_sentence = ""
            if active_allergies:
                allergy_sentence = (
                    " The active allergy rules for "
                    + ", ".join(active_allergies)
                    + " need restaurant-specific ingredient confirmation and "
                    "cross-contamination review."
                )
            risk_hints = [
                "Egg, meat garnish, broth, and gochujang need confirmation",
                *[
                    f"{allergen.title()} cross-contamination/cross-contact is not verified"
                    for allergen in active_allergies
                ],
            ]
            return self._make_turn(
                "Plant-forward bibimbap is a useful direction, but this synthetic menu does not "
                "verify every vegan detail. Egg, meat garnish, broth, and gochujang ingredients "
                "must be confirmed, so I will not label it as verified vegan." + allergy_sentence,
                ChatState.SAFETY_WARNING,
                [
                    Card(
                        type="category_recommendations",
                        title="Vegan direction—with checks still needed",
                        subtitle=(
                            "Unknown allergen evidence is excluded for the active severe allergy"
                            if severe_allergy
                            else "Vegan status remains unverified"
                        ),
                        data={
                            "categories": [
                                {
                                    "category": "Bibimbap",
                                    "description": vegan.cultural_description,
                                    "match_reasons": ["Plant-forward direction requested"],
                                    "risk_hints": risk_hints,
                                    "source_ids": [
                                        vegan.menu_id,
                                        vegan.merchant_id,
                                        *vegan.evidence_ids,
                                    ],
                                }
                            ]
                        },
                    )
                ],
                False,
                ["Find only explicitly verified options", "Review my active constraints"],
            )

        if "chicken kalguksu" in lowered:
            explained_menu = self.repository.get_menu("menu_003_01", profile)
            evidence = self.repository.get_evidence("menu_003_01")
            assert explained_menu
            knowledge = self.repository.get_grounded_menu_knowledge(
                "menu_003_01",
                query=user_text,
                option_item_ids=self._selected_option_ids("menu_003_01", active_needs),
            )
            explanation = {
                "cultural_analogy": explained_menu.cultural_description,
                "portion": (
                    f"Usually serves {explained_menu.serves_min}-{explained_menu.serves_max}"
                ),
                "unknown_fields": list(
                    dict.fromkeys([*explained_menu.risk_hints, *knowledge.unknowns])
                ),
                "evidence_ids": [item.evidence_id for item in evidence],
                "wiki_passages": [
                    passage.model_dump(mode="json") for passage in knowledge.passages
                ],
                "ingredient_claims": [
                    claim.model_dump(mode="json") for claim in knowledge.ingredient_claims
                ],
                "allergen_claims": [
                    claim.model_dump(mode="json") for claim in knowledge.allergen_claims
                ],
                "dietary_claims": [
                    claim.model_dump(mode="json") for claim in knowledge.dietary_claims
                ],
                "preparation_claims": [
                    claim.model_dump(mode="json") for claim in knowledge.preparation_claims
                ],
                "merchant_ingredient_claims": [
                    claim.model_dump(mode="json")
                    for claim in knowledge.merchant_ingredient_claims
                ],
                "grounded_claim_ids": knowledge.claim_ids,
                "grounded_passage_ids": [passage.chunk_id for passage in knowledge.passages],
                "is_synthetic": True,
            }
            return self._make_turn(
                "Chicken kalguksu is a warm, mild noodle-soup direction with thick handmade "
                "noodles and chicken broth. The synthetic sauce record marks shellfish absent, "
                "but kitchen cross-contamination remains unverified.",
                ChatState.MENU_EXPLANATION,
                [
                    Card(
                        type="menu_explanation",
                        title="What this dish will feel like",
                        subtitle="Taste, texture, portion, and unknowns",
                        data={
                            "menu": explained_menu.model_dump(mode="json"),
                            "explanation": explanation,
                        },
                    )
                ],
                False,
                [
                    "Recommend this dish when ready",
                    "Show dietary evidence",
                    "Explain another mild soup",
                ],
                dialogue_act=DialogueAct.EXPLAIN,
            )

        if any(phrase in lowered for phrase in ("red rice cake", "tteokbokki", "street")):
            classic = self.repository.get_menu("menu_002_01", profile)
            mild = self.repository.get_menu("menu_001_01", profile)
            evidence = self.repository.get_evidence("menu_002_01")
            assert classic and mild
            active_shellfish_allergy = "shellfish_allergy" in active_needs.dietary_rules
            spice_conflict = (
                active_needs.max_spiciness is not None
                and classic.spice_level > active_needs.max_spiciness
            )
            classic_eligible = self._menu_still_satisfies_active_constraints(
                classic.menu_id, profile, active_needs
            )
            mild_eligible = self._menu_still_satisfies_active_constraints(
                mild.menu_id, profile, active_needs
            )
            text = (
                "That sounds like tteokbokki: chewy rice cakes in a sweet-spicy gochujang sauce. "
                "The classic demo version is level 3 on YOBI's three-level spice scale."
            )
            conflict_labels: list[str] = []
            if active_shellfish_allergy:
                conflict_labels.append("active shellfish allergy")
                text += (
                    " Your active shellfish allergy conflicts with the synthetic menu "
                    "specification, so I would avoid and exclude the classic version. "
                    "Restaurant-specific cross-contact is not verified."
                )
            if spice_conflict:
                conflict_labels.append(f"active maximum spice {active_needs.max_spiciness} of 3")
                text += " Its spice level also exceeds your current maximum."
            if not classic_eligible and not conflict_labels:
                conflict_labels.append("current hard dietary constraints")
                text += " It does not pass the other hard dietary constraints currently saved."

            if conflict_labels:
                cards = [
                    Card(
                        type=(
                            "dietary_evidence" if active_shellfish_allergy else "menu_explanation"
                        ),
                        title="Why the classic version does not fit",
                        subtitle=" · ".join(conflict_labels),
                        data={
                            "menu": classic.model_dump(mode="json"),
                            "evidence": [item.model_dump(mode="json") for item in evidence],
                        },
                    )
                ]
                if mild_eligible:
                    text += (
                        " The rose version passes those active catalog filters; menu-specific "
                        "unknowns remain visible on its card."
                    )
                    cards.append(
                        Card(
                            type="menu_recommendations",
                            title="Alternative that fits the active constraints",
                            subtitle="Synthetic demo menu · not a safety guarantee",
                            data={"menus": [mild.model_dump(mode="json")]},
                        )
                    )
                state = ChatState.SAFETY_WARNING
            else:
                text += (
                    " It passes the hard constraints currently saved, while the card keeps "
                    "menu-specific unknowns visible."
                )
                cards = [
                    Card(
                        type="menu_recommendations",
                        title="Classic tteokbokki from the synthetic catalog",
                        subtitle="No known conflict with the current hard constraints",
                        data={"menus": [classic.model_dump(mode="json")]},
                    )
                ]
                state = ChatState.MENU_EXPLANATION
            return self._make_turn(
                text,
                state,
                cards,
                False,
                ["Show the evidence", "Find a different menu"],
            )

        comparison_category = self._catalog_category(user_text)
        if comparison_category and any(
            phrase in lowered for phrase in ("compare", "which place", "rose options", "비교", "차이")
        ):
            comparison = self._category_comparison_turn(
                profile,
                user_text,
                active_needs,
                DialogueAct.COMPARE,
            )
            if comparison is not None:
                return comparison

        latest_snapshot = self.repository.get_recommendation_snapshot(session.session_id)
        first_demo_is_visible = bool(
            latest_snapshot
            and any(
                candidate.menu_id == "menu_001_01"
                for candidate in latest_snapshot.result.candidates
            )
        )
        if first_demo_is_visible and any(
            phrase in lowered for phrase in ("choose seoul", "first place", "first option")
        ):
            options = self.repository.get_options("menu_001_01")
            self.repository.set_session_selection(
                session.session_id, ChatState.MENU_OPTIONS.value, "menu_001_01", "mer_001"
            )
            return self._make_turn(
                "Good choice. First, pick the spice level. Mild is the recommended demo default "
                "for your level 1 tolerance.",
                ChatState.MENU_OPTIONS,
                [
                    Card(
                        type="option_question",
                        title="1 of 4 · Spice level",
                        subtitle="One decision at a time",
                        data={"option_groups": [options[0].model_dump(mode="json")]},
                    )
                ],
                False,
                ["Mild", "Medium", "Go back"],
            )

        menus = self.repository.recommend_menus(user_text, profile, active_needs, limit=3)
        if not menus:
            return self._make_turn(
                "I could not find a menu that satisfies all of those constraints in the synthetic "
                "catalog. I will keep the constraints rather than quietly relax them. Which one "
                "could be flexible, if any?",
                ChatState.CLARIFICATION,
                [],
                False,
                ["Keep every constraint", "The budget can change", "Try another food style"],
                dialogue_act=DialogueAct.COLLECT_NEEDS,
            )
        need_summary = self._need_summary(active_needs, user_text)
        return self._make_turn(
            f"I have enough context now: {need_summary}. These are the strongest synthetic "
            "catalog matches that passed the current hard constraints. Menu-specific unknowns "
            "and cross-contact limits remain visible on each card.",
            ChatState.MENU_EXPLANATION,
            [
                Card(
                    type="menu_recommendations",
                    title="Grounded menu matches",
                    subtitle="Synthetic demo catalog",
                    data={"menus": [menu.model_dump(mode="json") for menu in menus]},
                )
            ],
            False,
            ["Compare these", "Something else", "Show dietary evidence"],
        )

    @staticmethod
    def _make_turn(
        text: str,
        state: ChatState,
        cards: list[Card],
        fallback_used: bool,
        suggested_replies: list[str] | None = None,
        dialogue_act: DialogueAct = DialogueAct.COLLECT_NEEDS,
        readiness: ReadinessDecision | None = None,
    ) -> AssistantTurn:
        return AssistantTurn(
            message_id=f"msg_{uuid4().hex}",
            text=text,
            state=state,
            cards=cards,
            suggested_replies=suggested_replies or [],
            dialogue_act=dialogue_act,
            readiness=readiness,
            fallback_used=fallback_used,
            created_at=datetime.now(timezone.utc),
        )
