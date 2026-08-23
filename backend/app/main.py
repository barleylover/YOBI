from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, model_validator

from app.api.errors import (
    not_found as _not_found,
)
from app.api.errors import (
    structured_recommendation_http_error as _structured_recommendation_http_error,
)
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event, safe_session_hash
from app.db.demo_address import DEMO_ADDRESS_PLACE_ID
from app.db.repository import YobiRepository
from app.dependencies import (
    get_chat_service,
    get_demo_control,
    get_menu_presentation_service,
    get_option_localization_service,
    get_repository,
    get_restaurant_note_translation_service,
    get_structured_recommendation_service,
)
from app.domain.address import normalize_address_text
from app.domain.dialogue import ConversationEventInput, ConversationEventResult, ConversationView
from app.domain.models import (
    AddressCandidate,
    CartItemInput,
    CartItemUpdate,
    CartPreview,
    Checkout,
    CheckoutCreate,
    DeliveryPreferenceInput,
    MerchantMenuPresentationPage,
    MerchantMenuPresentationRequest,
    Order,
    Profile,
    ProfileCreate,
    ProfileUpdate,
    RestaurantNoteTranslation,
    RestaurantNoteTranslationInput,
    Session,
    UserMessage,
)
from app.domain.preference_catalog import normalize_preference_locale
from app.domain.structured_recommendation import (
    FeaturedMenuCollection,
    FoodRankingCollection,
    FoodRankingSort,
    RecommendationBatchV2,
    RecommendationComparisonRequest,
    RecommendationComparisonV2,
    RecommendationCriteriaCommit,
    RecommendationCriteriaCommitResult,
    RecommendationCriteriaV2,
    RecommendationPreviewV2,
    RecommendationRequestInput,
)
from app.genai.providers import genai_configuration_errors
from app.genai.recommendation_generator import GROUNDING_DIAGNOSTICS_VERSION
from app.genai.response_limits import OUTPUT_LIMIT_RETRY_MULTIPLIER
from app.services.address_ocr import AddressCandidateTokenCodec, choose_address_ocr
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl, FailureMode
from app.services.menu_presentation import MenuPresentationService
from app.services.option_localization import OptionLocalizationService
from app.services.restaurant_note_translation import RestaurantNoteTranslationService
from app.services.structured_recommendation import StructuredRecommendationService

_RELEASE_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _release_metadata() -> dict[str, Any]:
    manifest_path = Path.cwd() / ".yobi-release-manifest"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return {"managed": False}
    try:
        values = dict(
            line.split("=", 1)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    except (OSError, ValueError):
        return {"managed": False}
    release_id = values.get("release_id", "")
    archive_sha256 = values.get("archive_sha256", "")
    source_git_commit = values.get("source_git_commit", "")
    if not (
        _RELEASE_ID_PATTERN.fullmatch(release_id)
        and _SHA256_PATTERN.fullmatch(archive_sha256)
        and _GIT_COMMIT_PATTERN.fullmatch(source_git_commit)
    ):
        return {"managed": False}
    return {
        "managed": True,
        "release_id": release_id,
        "archive_sha256": archive_sha256,
        "source_git_commit": source_git_commit,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    repository = get_repository()
    repository.initialize()
    try:
        yield
    finally:
        pool = getattr(repository, "pool", None)
        if pool is not None and hasattr(pool, "close"):
            pool.close()


app = FastAPI(
    title="YOBI MVP API",
    version="0.1.0",
    description="Multilingual food concierge and ordering API",
    lifespan=lifespan,
)
settings = get_settings()
logger = configure_logging(settings.log_level)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Demo-Control-Token", "Idempotency-Key"],
)


@app.middleware("http")
async def structured_request_log(request: Request, call_next: Any) -> Any:
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    started = monotonic()
    status_code = 500
    safe_error_code = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        safe_error_code = type(exc).__name__.upper()
        raise
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or "unmatched"
        log_event(
            logger,
            request_id=request_id,
            session_id_hash=safe_session_hash(request.url.path),
            endpoint=route_path,
            method=request.method,
            latency_ms=int((monotonic() - started) * 1000),
            tool=None,
            status=status_code,
            evidence_count=None,
            fallback=None,
            safe_error_code=safe_error_code,
        )


class SessionCreate(BaseModel):
    profile_id: str


class ManualAddressInput(BaseModel):
    hotel_name: str = Field(min_length=1, max_length=200)
    road_address: str = Field(min_length=3, max_length=500)
    postal_code: str = Field(default="", max_length=20)
    city: str = Field(default="Seoul", min_length=1, max_length=120)
    delivery_hint: str = Field(default="Please confirm the delivery location.", max_length=1000)


class AddressConfirm(BaseModel):
    candidate_token: str | None = Field(default=None, max_length=2000)
    manual: ManualAddressInput | None = None

    @model_validator(mode="after")
    def require_one_confirmation_source(self) -> AddressConfirm:
        if (self.candidate_token is None) == (self.manual is None):
            raise ValueError("Provide exactly one candidate token or manual address")
        return self


class AddressCandidateView(AddressCandidate):
    candidate_token: str


def _address_candidate_view(
    session_id: str,
    candidate: AddressCandidate,
    codec: AddressCandidateTokenCodec,
    source_image_hash: str | None,
) -> AddressCandidateView:
    display_candidate = candidate
    if candidate.place_id.startswith("hotel_demo_"):
        suffix = candidate.place_id.rsplit("_", 1)[-1]
        ordinal = int(suffix) if suffix.isdigit() else 1
        display_candidate = candidate.model_copy(
            update={
                "hotel_name": (
                    "YOBI Myeongdong Hotel"
                    if candidate.place_id == DEMO_ADDRESS_PLACE_ID
                    else f"YOBI Myeongdong Stay {ordinal:02d}"
                ),
                "road_address": (
                    "서울특별시 중구 을지로 21"
                    if candidate.place_id == DEMO_ADDRESS_PLACE_ID
                    else f"서울특별시 중구 퇴계로 {100 + ordinal}"
                ),
            }
        )
    return AddressCandidateView(
        **display_candidate.model_dump(),
        candidate_token=codec.encode(
            session_id,
            candidate,
            source_image_hash,
        ),
    )


class AddressUploadResult(BaseModel):
    candidates: list[AddressCandidateView]
    low_confidence: bool
    notice: str


class AddressResolveRequest(BaseModel):
    text: str = Field(min_length=2, max_length=500)


class DemoFailureMode(BaseModel):
    mode: FailureMode


class DemoResetRequest(BaseModel):
    session_id: str


def _require_session(repository: YobiRepository, session_id: str) -> Session:
    session = repository.get_session(session_id)
    if session is None:
        raise _not_found("SESSION_NOT_FOUND")
    return session


def _demo_authorized(
    x_demo_control_token: str | None = Header(default=None),
    current_settings: Settings = Depends(get_settings),
) -> None:
    expected = current_settings.demo_control_token.get_secret_value()
    if current_settings.app_env == "production" and (
        not expected or x_demo_control_token != expected
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN"})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "yobi-api"}


@app.get("/readyz")
def readyz(
    repository: YobiRepository = Depends(get_repository),
    current_settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        db = repository.status()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DB_NOT_READY"},
        ) from exc
    external_ready = (
        db.get("source_integrity_ready") is True
        and db.get("recommendation_ready") is True
    )
    normal_ready = (
        db.get("canonical_ready") is True and db.get("knowledge_ready") is True
    )
    if not (
        external_ready
        if db.get("catalog_mode") == "EXTERNAL_SOURCE"
        else normal_ready
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CATALOG_NOT_READY"},
        )
    genai_required = (
        current_settings.app_env == "production"
        or current_settings.oci_genai_serving_mode == "dedicated"
    )
    configuration_errors = genai_configuration_errors(current_settings)
    if configuration_errors:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "GENAI_NOT_READY",
                "errors": configuration_errors,
            },
        )
    readiness_checks = db.get("readiness_checks")
    wiki_eligibility_ready = bool(
        readiness_checks.get("wiki_eligibility_exactly_covers_membership_menus")
        if isinstance(readiness_checks, dict)
        else False
    )
    return {
        "status": "ready",
        "release": _release_metadata(),
        "database": db,
        "genai_required": genai_required,
        "genai": {
            "provider": current_settings.genai_provider,
            "serving_mode": current_settings.oci_genai_serving_mode,
            "admission_control": {
                "enabled": current_settings.oci_genai_admission_control_enabled,
                "max_concurrent_per_model": (
                    current_settings.oci_genai_max_concurrent_requests_per_model
                ),
                "min_interval_seconds": current_settings.oci_genai_min_interval_seconds,
                "rate_limit_cooldown_seconds": (
                    current_settings.oci_genai_rate_limit_cooldown_seconds
                ),
            },
            "configured": bool(
                current_settings.oci_genai_api_key.get_secret_value().strip()
                and current_settings.oci_genai_model.strip()
                and (
                    current_settings.oci_genai_serving_mode == "on_demand"
                    or current_settings.oci_genai_endpoint_id.strip()
                )
            ),
        },
        "structured_recommendation": {
            "grounding_diagnostics_version": GROUNDING_DIAGNOSTICS_VERSION,
            "model_id": current_settings.structured_recommendation_model,
            "presentation_model_id": current_settings.menu_presentation_model,
            "presentation_fallback_model_id": current_settings.oci_genai_fallback_model,
            "output_limit_retry_multiplier": OUTPUT_LIMIT_RETRY_MULTIPLIER,
            "option_localization_model_id": current_settings.option_localization_model,
            "option_localization_model_chain": [
                model.strip()
                for model in current_settings.option_localization_model_chain.split(",")
                if model.strip()
            ],
            "restaurant_note_model_chain": [
                model.strip()
                for model in current_settings.restaurant_note_model_chain.split(",")
                if model.strip()
            ],
            "selection_enabled": current_settings.recommendation_llm_selection_enabled,
            "candidate_limit": current_settings.recommendation_candidate_limit,
            "shortlist_limit": current_settings.recommendation_llm_shortlist_limit,
            "passages_per_menu": current_settings.recommendation_llm_passages_per_menu,
            "selection_max_output_tokens": (
                current_settings.recommendation_selection_max_output_tokens
            ),
            "selection_retry_max_output_tokens": min(
                current_settings.recommendation_selection_max_output_tokens
                * OUTPUT_LIMIT_RETRY_MULTIPLIER,
                current_settings.oci_genai_max_output_tokens,
            ),
            "max_output_tokens": current_settings.structured_recommendation_max_output_tokens,
            "presentation_max_output_tokens": (
                current_settings.menu_presentation_max_output_tokens
            ),
            "presentation_retry_max_output_tokens": min(
                current_settings.menu_presentation_max_output_tokens
                * OUTPUT_LIMIT_RETRY_MULTIPLIER,
                current_settings.oci_genai_max_output_tokens,
            ),
            "option_localization_max_output_tokens": (
                current_settings.option_localization_max_output_tokens
            ),
            "menu_presentation_prompt_version": (
                current_settings.menu_presentation_prompt_version
            ),
            "option_localization_prompt_version": (
                current_settings.option_localization_prompt_version
            ),
            "restaurant_note_prompt_version": (
                current_settings.restaurant_note_prompt_version
            ),
            "demo_option_limits": {
                "groups": current_settings.demo_option_group_limit,
                "items_per_group": current_settings.demo_option_items_per_group_limit,
                "total_items": current_settings.demo_option_item_total_limit,
            },
            "ranking_policy_version": db.get("ranking_policy_version"),
            "feature_count": db.get("feature_count", 0),
            "feature_manifest_sha256": db.get("feature_manifest_sha256"),
            "wiki_eligible_menu_count": db.get("wiki_eligible_menu_count", 0),
            "wiki_eligibility_ready": wiki_eligibility_ready,
            "semantic_channel_status": db.get("semantic_channel_status"),
            "semantic_vector_ready": db.get("vector_ready") is True,
            "ready": bool(
                current_settings.recommendation_llm_selection_enabled
                and current_settings.structured_recommendation_model
                == "openai.gpt-oss-120b"
                and current_settings.menu_presentation_model == "xai.grok-4.3"
                and current_settings.oci_genai_fallback_model
                == "openai.gpt-oss-120b"
                and current_settings.option_localization_model == "openai.gpt-oss-20b"
                and current_settings.option_localization_model_chain
                == "openai.gpt-oss-20b,openai.gpt-oss-120b"
                and current_settings.restaurant_note_model
                == "meta.llama-4-maverick-17b-128e-instruct-fp8"
                and current_settings.restaurant_note_model_chain
                == (
                    "meta.llama-4-maverick-17b-128e-instruct-fp8,"
                    "openai.gpt-oss-20b"
                )
                and current_settings.recommendation_llm_passages_per_menu == 2
                and current_settings.recommendation_selection_max_output_tokens == 2048
                and current_settings.structured_recommendation_max_output_tokens == 16384
                and current_settings.menu_presentation_max_output_tokens == 4096
                and current_settings.oci_genai_max_output_tokens >= 8192
                and current_settings.option_localization_max_output_tokens == 16384
                and db.get("recommendation_ready") is True
            ),
        },
    }


@app.post("/api/v1/profiles", response_model=Profile, status_code=status.HTTP_201_CREATED)
def create_profile(
    data: ProfileCreate, repository: YobiRepository = Depends(get_repository)
) -> Profile:
    try:
        return repository.create_profile(data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": str(exc)},
        ) from exc


@app.get("/api/v1/profiles/{profile_id}", response_model=Profile)
def get_profile(profile_id: str, repository: YobiRepository = Depends(get_repository)) -> Profile:
    profile = repository.get_profile(profile_id)
    if not profile:
        raise _not_found("PROFILE_NOT_FOUND")
    return profile


@app.patch("/api/v1/profiles/{profile_id}", response_model=Profile)
def update_profile(
    profile_id: str,
    data: ProfileUpdate,
    repository: YobiRepository = Depends(get_repository),
) -> Profile:
    try:
        profile = repository.update_profile(profile_id, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": str(exc)},
        ) from exc
    if profile is None:
        raise _not_found("PROFILE_NOT_FOUND")
    return profile


@app.delete("/api/v1/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str, repository: YobiRepository = Depends(get_repository)) -> None:
    if not repository.delete_profile(profile_id):
        raise _not_found("PROFILE_NOT_FOUND")


@app.post("/api/v1/sessions", response_model=Session, status_code=status.HTTP_201_CREATED)
def create_session(
    data: SessionCreate, repository: YobiRepository = Depends(get_repository)
) -> Session:
    try:
        return repository.create_session(data.profile_id)
    except KeyError as exc:
        raise _not_found("PROFILE_NOT_FOUND") from exc


@app.get("/api/v1/sessions/{session_id}", response_model=Session)
def get_session(session_id: str, repository: YobiRepository = Depends(get_repository)) -> Session:
    session = repository.get_session(session_id)
    if not session:
        raise _not_found("SESSION_NOT_FOUND")
    return session


@app.post("/api/v1/sessions/{session_id}/reset", response_model=Session)
def reset_session(session_id: str, repository: YobiRepository = Depends(get_repository)) -> Session:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    repository.reset_session(session_id)
    return repository.get_session(session_id)  # type: ignore[return-value]


def _resolve_session_profile(
    repository: YobiRepository, session_id: str
) -> tuple[Session, Profile]:
    session = _require_session(repository, session_id)
    profile = repository.get_profile(session.profile_id)
    if not profile:
        raise _not_found("PROFILE_NOT_FOUND")
    return session, profile


@app.get("/api/v1/recommendation/preferences/catalog")
def get_recommendation_preference_catalog(
    response: Response,
    locale: str = "en",
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    repository: YobiRepository = Depends(get_repository),
) -> Any:
    try:
        payload = repository.get_preference_catalog(locale)
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc
    payload = {
        **payload,
        "locale": normalize_preference_locale(str(payload.get("locale") or locale)),
    }
    etag_seed = ":".join(
        (
            str(payload.get("locale", "en")),
            str(payload.get("catalog_version", "")),
            str(payload.get("knowledge_release_id", "")),
            str(payload.get("support_manifest_sha256", "")),
            str(payload.get("feature_manifest_sha256", "")),
            str(payload.get("ranking_policy_version", "")),
        )
    )
    etag = f'"{hashlib.sha256(etag_seed.encode()).hexdigest()}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=300"
    if if_none_match == etag:
        response.status_code = status.HTTP_304_NOT_MODIFIED
        return None
    return payload


@app.post(
    "/api/v1/sessions/{session_id}/structured-recommendations/preview",
    response_model=RecommendationPreviewV2,
)
def preview_structured_recommendation(
    session_id: str,
    criteria: RecommendationCriteriaV2,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> RecommendationPreviewV2:
    session = _require_session(repository, session_id)
    try:
        return recommendation_service.preview(session, criteria)
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc


@app.put(
    "/api/v1/sessions/{session_id}/recommendation-criteria",
    response_model=RecommendationCriteriaCommitResult,
)
def put_recommendation_criteria(
    session_id: str,
    commit: RecommendationCriteriaCommit,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> RecommendationCriteriaCommitResult:
    session = _require_session(repository, session_id)
    try:
        record = recommendation_service.commit_criteria(session, commit)
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc
    return RecommendationCriteriaCommitResult(
        session_id=record.session_id,
        criteria=record.criteria,
        criteria_version=record.criteria_version,
        state_version=record.state_version,
        criteria_hash=record.criteria_hash,
        created_at=record.created_at,
    )


@app.post(
    "/api/v1/sessions/{session_id}/recommendations",
    response_model=RecommendationBatchV2,
    responses={202: {"model": RecommendationBatchV2}},
)
def post_structured_recommendation(
    session_id: str,
    data: RecommendationRequestInput,
    background_tasks: BackgroundTasks,
    response: Response,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> RecommendationBatchV2:
    session, profile = _resolve_session_profile(repository, session_id)
    try:
        batch, should_process = recommendation_service.begin_recommendation(
            session,
            profile,
            data,
        )
        if should_process:
            background_tasks.add_task(
                recommendation_service.process_reserved_recommendation,
                session,
                profile,
                data,
            )
        if batch.status == "PENDING":
            response.status_code = status.HTTP_202_ACCEPTED
        return batch
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc


@app.get(
    "/api/v1/sessions/{session_id}/recommendation-requests/{request_id}",
    response_model=RecommendationBatchV2,
)
def get_structured_recommendation_request(
    session_id: str,
    request_id: str,
    background_tasks: BackgroundTasks,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> RecommendationBatchV2:
    session, profile = _resolve_session_profile(repository, session_id)
    result, resumable = recommendation_service.recover_request(
        session,
        profile,
        request_id,
    )
    if result is None:
        raise _not_found("RECOMMENDATION_REQUEST_NOT_FOUND")
    if resumable is not None:
        background_tasks.add_task(
            recommendation_service.process_reserved_recommendation,
            session,
            profile,
            resumable,
        )
    return result


@app.post(
    "/api/v1/sessions/{session_id}/recommendation-requests/{request_id}/cancel",
)
def cancel_structured_recommendation_request(
    session_id: str,
    request_id: str,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> dict[str, bool]:
    _require_session(repository, session_id)
    if not recommendation_service.cancel_request(session_id, request_id):
        raise _not_found("RECOMMENDATION_REQUEST_NOT_FOUND")
    return {"cancelled": True}


@app.post(
    "/api/v1/sessions/{session_id}/restaurant-note-translations",
    response_model=RestaurantNoteTranslation,
)
def translate_restaurant_note(
    session_id: str,
    data: RestaurantNoteTranslationInput,
    repository: YobiRepository = Depends(get_repository),
    translation_service: RestaurantNoteTranslationService = Depends(
        get_restaurant_note_translation_service
    ),
) -> RestaurantNoteTranslation:
    _require_session(repository, session_id)
    return translation_service.translate(session_id, data)


@app.post(
    "/api/v1/sessions/{session_id}/recommendation-comparisons",
    response_model=RecommendationComparisonV2,
)
def post_recommendation_comparison(
    session_id: str,
    data: RecommendationComparisonRequest,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> RecommendationComparisonV2:
    session, profile = _resolve_session_profile(repository, session_id)
    try:
        return recommendation_service.compare_recommendations(session, profile, data)
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc


@app.get(
    "/api/v1/sessions/{session_id}/food-rankings",
    response_model=FoodRankingCollection,
)
def get_food_rankings(
    session_id: str,
    sort: FoodRankingSort = "review_count",
    limit: int = Query(default=20, ge=1, le=20),
    repository: YobiRepository = Depends(get_repository),
) -> FoodRankingCollection:
    _require_session(repository, session_id)
    try:
        return repository.list_food_rankings(session_id, sort, limit)
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc


@app.get(
    "/api/v1/sessions/{session_id}/featured/kpop-demon-hunters",
    response_model=FeaturedMenuCollection,
)
def get_kpop_demon_hunters_feature(
    session_id: str,
    repository: YobiRepository = Depends(get_repository),
) -> FeaturedMenuCollection:
    _require_session(repository, session_id)
    try:
        return repository.list_kpop_demon_hunters_feature(session_id)
    except Exception as exc:
        raise _structured_recommendation_http_error(exc) from exc


@app.post("/api/v1/sessions/{session_id}/messages")
def post_message(
    session_id: str,
    data: UserMessage,
    repository: YobiRepository = Depends(get_repository),
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    session, profile = _resolve_session_profile(repository, session_id)
    try:
        turn = chat_service.respond(
            session,
            profile,
            data.content,
            data.intent,
            request_id=data.request_id,
        )
    except RuntimeError as exc:
        if str(exc) == "CHAT_STATE_VERSION_CONFLICT":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHAT_STATE_VERSION_CONFLICT"},
            ) from exc
        raise
    except ValueError as exc:
        if str(exc) == "CHAT_REQUEST_ID_REUSED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHAT_REQUEST_ID_REUSED"},
            ) from exc
        raise
    return turn.model_dump(mode="json")


@app.post("/api/v1/sessions/{session_id}/messages/stream")
def stream_message(
    session_id: str,
    data: UserMessage,
    repository: YobiRepository = Depends(get_repository),
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    session, profile = _resolve_session_profile(repository, session_id)

    def events() -> Any:
        yield "event: message_start\ndata: {}\n\n"
        try:
            turn = chat_service.respond(
                session,
                profile,
                data.content,
                data.intent,
                request_id=data.request_id,
            )
        except Exception as exc:
            code = str(exc) if str(exc) in {
                "CHAT_STATE_VERSION_CONFLICT",
                "CHAT_REQUEST_ID_REUSED",
            } else "CHAT_RESPONSE_FAILED"
            yield f"event: error\ndata: {json.dumps({'code': code})}\n\n"
            return
        if turn.cards:
            yield 'event: status\ndata: {"text":"Checking menu details…"}\n\n'
            yield 'event: tool_started\ndata: {"label":"Reviewing grounded menu data…"}\n\n'
            yield 'event: tool_completed\ndata: {"label":"Grounded check complete"}\n\n'
        else:
            yield 'event: status\ndata: {"text":"Understanding your meal needs…"}\n\n'
        if turn.fallback_used:
            yield 'event: warning\ndata: {"text":"Continuing with the available menu data."}\n\n'
        for start in range(0, len(turn.text), 80):
            chunk = turn.text[start : start + 80]
            yield f"event: text_delta\ndata: {json.dumps({'text': chunk})}\n\n"
        for card in turn.cards:
            yield f"event: card\ndata: {json.dumps(card.model_dump(mode='json'))}\n\n"
        yield f"event: message_end\ndata: {json.dumps(turn.model_dump(mode='json'))}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/v1/sessions/{session_id}/messages")
def list_messages(
    session_id: str, repository: YobiRepository = Depends(get_repository)
) -> list[dict[str, str]]:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    return repository.list_messages(session_id)


@app.get("/api/v1/sessions/{session_id}/conversation", response_model=ConversationView)
def get_conversation(
    session_id: str,
    repository: YobiRepository = Depends(get_repository),
    recommendation_service: StructuredRecommendationService = Depends(
        get_structured_recommendation_service
    ),
) -> ConversationView:
    session, profile = _resolve_session_profile(repository, session_id)
    criteria = repository.get_recommendation_criteria(session_id)
    latest_request = repository.get_latest_recommendation_request(session_id)
    active_request = repository.get_latest_recommendation_request(session_id, active_only=True)
    latest_batch = (
        recommendation_service.get_request(session_id, latest_request.request_id)
        if latest_request is not None
        else None
    )
    active_batch = (
        recommendation_service.get_request(session_id, active_request.request_id)
        if active_request is not None
        else None
    )
    selected_menu = (
        repository.get_menu(session.meal_need_state.selected_menu_id, profile)
        if session.meal_need_state.selected_menu_id
        else None
    )
    return ConversationView(
        session_id=session.session_id,
        state_version=session.state_version,
        meal_need_state=session.meal_need_state,
        messages=repository.list_messages(session_id),
        latest_snapshot=repository.get_recommendation_snapshot(session_id),
        recommendation_criteria=(
            criteria.criteria.model_dump(mode="json") if criteria is not None else None
        ),
        criteria_version=criteria.criteria_version if criteria is not None else None,
        latest_recommendation=(
            latest_batch.model_dump(mode="json") if latest_batch is not None else None
        ),
        active_recommendation=(
            active_batch.model_dump(mode="json") if active_batch is not None else None
        ),
        selected_menu=(
            selected_menu.model_dump(mode="json") if selected_menu is not None else None
        ),
    )


@app.post(
    "/api/v1/sessions/{session_id}/events",
    response_model=ConversationEventResult,
)
def post_conversation_event(
    session_id: str,
    event: ConversationEventInput,
    repository: YobiRepository = Depends(get_repository),
    chat_service: ChatService = Depends(get_chat_service),
) -> ConversationEventResult:
    if repository.get_session(session_id) is None:
        raise _not_found("SESSION_NOT_FOUND")
    try:
        with chat_service.session_guard(session_id):
            return repository.apply_conversation_event(session_id, event)
    except KeyError as exc:
        raise _not_found(str(exc).strip("'")) from exc
    except RuntimeError as exc:
        if str(exc) == "CHAT_STATE_VERSION_CONFLICT":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CHAT_STATE_VERSION_CONFLICT"},
            ) from exc
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": str(exc)},
        ) from exc


@app.get("/api/v1/menus/{menu_id}/options")
def get_menu_options(
    menu_id: str,
    session_id: str | None = Query(default=None),
    precomputed_only: bool = Query(default=False),
    repository: YobiRepository = Depends(get_repository),
    option_localization_service: OptionLocalizationService = Depends(
        get_option_localization_service
    ),
) -> list[dict[str, Any]]:
    if session_id is not None:
        _require_session(repository, session_id)
    # Discovery collections remain deterministic: the service can read complete
    # release/runtime localizations but precomputed_only has no generation path.
    groups = option_localization_service.get_options(
        menu_id,
        session_id,
        precomputed_only=precomputed_only,
    )
    return [
        group.model_dump(mode="json")
        for group in groups
    ]


@app.get("/api/v1/menus/{menu_id}/evidence")
def get_menu_evidence(
    menu_id: str, repository: YobiRepository = Depends(get_repository)
) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repository.get_evidence(menu_id)]


@app.get("/api/v1/sessions/{session_id}/merchants/{merchant_id}/menus")
def list_merchant_menus(
    session_id: str,
    merchant_id: str,
    exclude: str = "",
    repository: YobiRepository = Depends(get_repository),
) -> list[dict[str, Any]]:
    session, profile = _resolve_session_profile(repository, session_id)
    excluded_menu_ids = [value for value in exclude.split(",") if value]
    return [
        menu.model_dump(mode="json")
        for menu in repository.list_merchant_menus(
            merchant_id,
            profile,
            excluded_menu_ids,
            limit=12,
            meal_need_state=session.meal_need_state,
        )
    ]


@app.post(
    "/api/v1/sessions/{session_id}/merchants/{merchant_id}/menu-presentations",
    response_model=MerchantMenuPresentationPage,
)
def list_merchant_menu_presentations(
    session_id: str,
    merchant_id: str,
    data: MerchantMenuPresentationRequest,
    repository: YobiRepository = Depends(get_repository),
    presentation_service: MenuPresentationService = Depends(
        get_menu_presentation_service
    ),
) -> MerchantMenuPresentationPage:
    _require_session(repository, session_id)
    return presentation_service.list_presentations(session_id, merchant_id, data)


def _validate_image(
    data: bytes,
    content_type: str | None,
    filename: str | None,
    max_bytes: int,
) -> None:
    if not data or len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "UPLOAD_SIZE_INVALID"},
        )
    allowed = {"image/png", "image/jpeg", "image/webp"}
    if content_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "UNSUPPORTED_IMAGE_TYPE"},
        )
    extension = Path(filename or "").suffix.lower()
    expected_extensions = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
    }
    if extension not in expected_extensions[content_type]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "IMAGE_EXTENSION_MISMATCH"},
        )
    magic_ok = (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")
    )
    if not magic_ok:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"code": "IMAGE_MAGIC_BYTE_INVALID"},
        )
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "IMAGE_DECODE_FAILED"},
        ) from exc


@app.post(
    "/api/v1/sessions/{session_id}/address/attachments",
    response_model=AddressUploadResult,
)
async def upload_address(
    session_id: str,
    file: UploadFile = File(...),
    repository: YobiRepository = Depends(get_repository),
    current_settings: Settings = Depends(get_settings),
) -> AddressUploadResult:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    data = await file.read(current_settings.max_upload_mb * 1024 * 1024 + 1)
    _validate_image(
        data,
        file.content_type,
        file.filename,
        current_settings.max_upload_mb * 1024 * 1024,
    )
    digest = hashlib.sha256(data).hexdigest()
    filename = (file.filename or "").lower()
    ocr = choose_address_ocr(current_settings)
    try:
        extracted_text = ocr.extract_text(data)
    except RuntimeError:
        extracted_text = ""
    parsed_text = ocr.parse_booking_fields(extracted_text)
    if not parsed_text:
        parsed_text = (
            "YOBI Myeongdong Hotel" if "yobi" in filename and "booking" in filename else filename
        )
    candidates = ocr.resolve_place_candidates(repository, parsed_text, digest)
    if extracted_text:
        candidates = [
            candidate.model_copy(update={"source": "ocr"})
            if candidate.confidence < 1.0
            else candidate
            for candidate in candidates
        ]
    codec = AddressCandidateTokenCodec(current_settings)
    views = [
        _address_candidate_view(session_id, candidate, codec, digest)
        for candidate in candidates
    ]
    fixed_demo_candidate = bool(candidates and candidates[0].place_id == DEMO_ADDRESS_PLACE_ID)
    low_confidence = not candidates or (
        not fixed_demo_candidate and candidates[0].confidence < 0.8
    )
    return AddressUploadResult(
        candidates=views,
        low_confidence=low_confidence,
        notice=(
            "This booking image uses the prepared YOBI Myeongdong delivery address. "
            "Confirm the address to continue."
            if fixed_demo_candidate
            else "The booking image matched a grounded address candidate. Confirm the address."
            if not low_confidence
            else "OCR confidence is low. Review the candidate or enter the address manually."
        ),
    )


@app.post(
    "/api/v1/sessions/{session_id}/address/resolve",
    response_model=AddressUploadResult,
)
def resolve_address_text(
    session_id: str,
    data: AddressResolveRequest,
    repository: YobiRepository = Depends(get_repository),
    current_settings: Settings = Depends(get_settings),
) -> AddressUploadResult:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    candidates = repository.resolve_address(data.text)
    codec = AddressCandidateTokenCodec(current_settings)
    views = [
        _address_candidate_view(session_id, candidate, codec, None)
        for candidate in candidates
    ]
    fixed_demo_candidate = bool(candidates and candidates[0].place_id == DEMO_ADDRESS_PLACE_ID)
    low_confidence = not candidates or (
        not fixed_demo_candidate and candidates[0].confidence < 0.8
    )
    return AddressUploadResult(
        candidates=views,
        low_confidence=low_confidence,
        notice=(
            "Address search found the prepared YOBI Myeongdong delivery address. "
            "Confirm the address to continue."
            if fixed_demo_candidate
            else "We found a matching place. Confirm the full road address."
            if not low_confidence
            else "No confident place match was found. Enter or edit the address manually."
        ),
    )


def _save_address_in_active_area(
    repository: YobiRepository,
    session_id: str,
    candidate: AddressCandidate,
    source_image_hash: str | None = None,
) -> str:
    try:
        return repository.save_address(session_id, candidate, source_image_hash)
    except ValueError as exc:
        if str(exc) != "ADDRESS_OUTSIDE_SERVICE_AREA":
            raise
        raise HTTPException(
            status_code=422,
            detail={"code": "ADDRESS_OUTSIDE_SERVICE_AREA"},
        ) from exc


@app.post("/api/v1/sessions/{session_id}/address/confirm")
def confirm_address(
    session_id: str,
    data: AddressConfirm,
    repository: YobiRepository = Depends(get_repository),
    current_settings: Settings = Depends(get_settings),
) -> dict[str, str]:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    if data.manual is not None:
        manual = data.manual
        candidates = repository.resolve_address(
            " ".join(
                (manual.hotel_name, manual.road_address, manual.postal_code, manual.city)
            )
        )
        canonical = next(
            (
                candidate
                for candidate in candidates
                if candidate.place_id != "manual"
                and candidate.confidence >= 0.8
                and candidate.service_area_id
                and normalize_address_text(candidate.road_address)
                == normalize_address_text(manual.road_address)
                and (
                    not normalize_address_text(manual.postal_code)
                    or normalize_address_text(candidate.postal_code)
                    == normalize_address_text(manual.postal_code)
                )
                and normalize_address_text(candidate.city)
                == normalize_address_text(manual.city)
            ),
            None,
        )
        if canonical is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "ADDRESS_OUTSIDE_SERVICE_AREA"},
            )
        candidate = AddressCandidate(
            place_id="manual",
            hotel_name=manual.hotel_name,
            road_address=manual.road_address,
            postal_code=manual.postal_code,
            city=manual.city,
            service_area_id=canonical.service_area_id,
            delivery_hint=manual.delivery_hint,
            confidence=canonical.confidence,
            source="manual",
            needs_confirmation=True,
        )
        return {
            "address_ref_id": _save_address_in_active_area(
                repository, session_id, candidate
            )
        }
    try:
        claims = AddressCandidateTokenCodec(current_settings).decode(
            data.candidate_token or "", session_id
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ADDRESS_CANDIDATE_TOKEN_INVALID"},
        ) from exc
    stored_candidate = repository.get_address_candidate(str(claims["place_id"]))
    if stored_candidate is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "ADDRESS_OUTSIDE_SERVICE_AREA"},
        )
    candidate = AddressCandidate(
        **stored_candidate.model_dump(exclude={"source", "confidence"}),
        source=claims["source"],
        confidence=float(claims["confidence"]),
    )
    return {
        "address_ref_id": _save_address_in_active_area(
            repository,
            session_id,
            candidate,
            str(claims["source_image_hash"]) if claims.get("source_image_hash") else None,
        )
    }


@app.get("/api/v1/sessions/{session_id}/cart", response_model=CartPreview)
def get_cart(session_id: str, repository: YobiRepository = Depends(get_repository)) -> CartPreview:
    _require_session(repository, session_id)
    return repository.get_cart(session_id)


@app.post("/api/v1/sessions/{session_id}/cart/items", response_model=CartPreview)
def add_cart_item(
    session_id: str,
    data: CartItemInput,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    repository: YobiRepository = Depends(get_repository),
) -> CartPreview:
    _require_session(repository, session_id)
    if idempotency_key is not None and not 8 <= len(idempotency_key) <= 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_IDEMPOTENCY_KEY"},
        )
    try:
        return repository.add_cart_item(session_id, data, idempotency_key)
    except KeyError as exc:
        raise _not_found("MENU_NOT_FOUND") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.patch(
    "/api/v1/sessions/{session_id}/cart/items/{cart_item_id}",
    response_model=CartPreview,
)
def update_cart_item(
    session_id: str,
    cart_item_id: str,
    data: CartItemUpdate,
    repository: YobiRepository = Depends(get_repository),
) -> CartPreview:
    _require_session(repository, session_id)
    try:
        return repository.update_cart_item(session_id, cart_item_id, data)
    except KeyError as exc:
        raise _not_found("CART_ITEM_NOT_FOUND") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.delete(
    "/api/v1/sessions/{session_id}/cart/items/{cart_item_id}",
    response_model=CartPreview,
)
def delete_cart_item(
    session_id: str,
    cart_item_id: str,
    repository: YobiRepository = Depends(get_repository),
) -> CartPreview:
    _require_session(repository, session_id)
    try:
        return repository.delete_cart_item(session_id, cart_item_id)
    except KeyError as exc:
        raise _not_found("CART_ITEM_NOT_FOUND") from exc


@app.patch("/api/v1/sessions/{session_id}/delivery", response_model=CartPreview)
def update_delivery(
    session_id: str,
    data: DeliveryPreferenceInput,
    repository: YobiRepository = Depends(get_repository),
) -> CartPreview:
    _require_session(repository, session_id)
    try:
        return repository.update_delivery(session_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.post("/api/v1/sessions/{session_id}/cart/confirm", response_model=CartPreview)
def confirm_cart(
    session_id: str, repository: YobiRepository = Depends(get_repository)
) -> CartPreview:
    _require_session(repository, session_id)
    try:
        return repository.confirm_cart(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.post("/api/v1/sessions/{session_id}/checkout", response_model=Checkout)
def create_checkout(
    session_id: str,
    data: CheckoutCreate,
    repository: YobiRepository = Depends(get_repository),
) -> Checkout:
    _require_session(repository, session_id)
    try:
        return repository.create_checkout(session_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.get("/api/v1/checkout/{checkout_id}", response_model=Checkout)
def get_checkout(
    checkout_id: str, repository: YobiRepository = Depends(get_repository)
) -> Checkout:
    checkout = repository.get_checkout(checkout_id)
    if not checkout:
        raise _not_found("CHECKOUT_NOT_FOUND")
    return checkout


def _payment_update(
    checkout_id: str,
    payment_status: Literal["SUCCEEDED", "FAILED", "CANCELED"],
    repository: YobiRepository,
    control: DemoControl,
) -> Checkout:
    if control.mode == "force_payment_failure" and payment_status == "SUCCEEDED":
        payment_status = "FAILED"
    try:
        return repository.update_checkout(checkout_id, payment_status)
    except KeyError as exc:
        raise _not_found("CHECKOUT_NOT_FOUND") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.post("/api/v1/checkout/{checkout_id}/mock-success", response_model=Checkout)
def mock_success(
    checkout_id: str,
    repository: YobiRepository = Depends(get_repository),
    control: DemoControl = Depends(get_demo_control),
) -> Checkout:
    return _payment_update(checkout_id, "SUCCEEDED", repository, control)


@app.post("/api/v1/checkout/{checkout_id}/mock-failure", response_model=Checkout)
def mock_failure(
    checkout_id: str,
    repository: YobiRepository = Depends(get_repository),
    control: DemoControl = Depends(get_demo_control),
) -> Checkout:
    return _payment_update(checkout_id, "FAILED", repository, control)


@app.post("/api/v1/checkout/{checkout_id}/cancel", response_model=Checkout)
def cancel_checkout(
    checkout_id: str,
    repository: YobiRepository = Depends(get_repository),
    control: DemoControl = Depends(get_demo_control),
) -> Checkout:
    return _payment_update(checkout_id, "CANCELED", repository, control)


@app.get("/api/v1/orders/{order_id}", response_model=Order)
def get_order(order_id: str, repository: YobiRepository = Depends(get_repository)) -> Order:
    order = repository.get_order(order_id)
    if not order:
        raise _not_found("ORDER_NOT_FOUND")
    return order


@app.get("/api/v1/demo/status", dependencies=[Depends(_demo_authorized)])
def demo_status(
    repository: YobiRepository = Depends(get_repository),
    control: DemoControl = Depends(get_demo_control),
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    return {
        "api": "ok",
        "database": repository.status(),
        "genai": "configured" if chat_service.agent.configured else "fallback-only",
        "fallback_mode": control.mode,
        "synthetic_data": True,
    }


@app.post("/api/v1/demo/reset", dependencies=[Depends(_demo_authorized)])
def reset_demo_session(
    data: DemoResetRequest,
    repository: YobiRepository = Depends(get_repository),
    control: DemoControl = Depends(get_demo_control),
) -> dict[str, str]:
    if not repository.get_session(data.session_id):
        raise _not_found("SESSION_NOT_FOUND")
    repository.reset_session(data.session_id)
    control.set_mode("normal")
    return {"session_id": data.session_id, "status": "reset"}


@app.post("/api/v1/demo/failure-mode", dependencies=[Depends(_demo_authorized)])
def set_failure_mode(
    data: DemoFailureMode, control: DemoControl = Depends(get_demo_control)
) -> dict[str, str]:
    control.set_mode(data.mode)
    return {"mode": data.mode}
