from functools import lru_cache

from app.core.config import get_settings
from app.db.oracle_repository import OracleYobiRepository
from app.db.repository import YobiRepository
from app.db.sqlite_repository import SQLiteYobiRepository
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl
from app.services.menu_presentation import MenuPresentationService
from app.services.restaurant_note_translation import RestaurantNoteTranslationService
from app.services.structured_recommendation import StructuredRecommendationService


@lru_cache(maxsize=1)
def get_repository() -> YobiRepository:
    settings = get_settings()
    repository: YobiRepository
    if settings.demo_db_backend == "oracle":
        repository = OracleYobiRepository(settings)
    else:
        repository = SQLiteYobiRepository(settings.sqlite_path)
    repository.initialize()
    return repository


@lru_cache(maxsize=1)
def get_demo_control() -> DemoControl:
    return DemoControl()


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService(get_repository(), get_settings(), get_demo_control())


@lru_cache(maxsize=1)
def get_structured_recommendation_service() -> StructuredRecommendationService:
    return StructuredRecommendationService(
        get_repository(),
        get_settings(),
        get_demo_control(),
    )


@lru_cache(maxsize=1)
def get_restaurant_note_translation_service() -> RestaurantNoteTranslationService:
    return RestaurantNoteTranslationService(get_repository(), get_settings())


@lru_cache(maxsize=1)
def get_menu_presentation_service() -> MenuPresentationService:
    return MenuPresentationService(get_repository(), get_settings())
