from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_event, safe_session_hash
from app.db.repository import YobiRepository
from app.dependencies import get_chat_service, get_demo_control, get_repository
from app.domain.models import (
    AddressCandidate,
    CartItemInput,
    CartPreview,
    Checkout,
    CheckoutCreate,
    DeliveryPreferenceInput,
    Order,
    Profile,
    ProfileCreate,
    Session,
    UserMessage,
)
from app.services.chat_service import ChatService
from app.services.demo_control import DemoControl, FailureMode


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
    description="Synthetic-data food concierge and mock ordering API",
    lifespan=lifespan,
)
settings = get_settings()
logger = configure_logging(settings.log_level)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
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


class AddressConfirm(BaseModel):
    candidate: AddressCandidate


class AddressUploadResult(BaseModel):
    attachment_hash: str
    candidates: list[AddressCandidate]
    low_confidence: bool
    notice: str


class DemoFailureMode(BaseModel):
    mode: FailureMode


def _not_found(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": code})


def _demo_authorized(
    x_demo_control_token: str | None = Header(default=None),
    current_settings: Settings = Depends(get_settings),
) -> None:
    expected = current_settings.demo_control_token.get_secret_value()
    if current_settings.app_env == "production" and (not expected or x_demo_control_token != expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN"})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "yobi-api"}


@app.get("/readyz")
def readyz(repository: YobiRepository = Depends(get_repository)) -> dict[str, Any]:
    try:
        db = repository.status()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DB_NOT_READY"},
        ) from exc
    return {"status": "ready", "database": db, "genai_required": False}


@app.post("/api/v1/profiles", response_model=Profile, status_code=status.HTTP_201_CREATED)
def create_profile(
    data: ProfileCreate, repository: YobiRepository = Depends(get_repository)
) -> Profile:
    try:
        return repository.create_profile(data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": str(exc)},
        ) from exc


@app.get("/api/v1/profiles/{profile_id}", response_model=Profile)
def get_profile(profile_id: str, repository: YobiRepository = Depends(get_repository)) -> Profile:
    profile = repository.get_profile(profile_id)
    if not profile:
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
    session = repository.get_session(session_id)
    if not session:
        raise _not_found("SESSION_NOT_FOUND")
    profile = repository.get_profile(session.profile_id)
    if not profile:
        raise _not_found("PROFILE_NOT_FOUND")
    return session, profile


@app.post("/api/v1/sessions/{session_id}/messages")
def post_message(
    session_id: str,
    data: UserMessage,
    repository: YobiRepository = Depends(get_repository),
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    session, profile = _resolve_session_profile(repository, session_id)
    return chat_service.respond(session, profile, data.content).model_dump(mode="json")


@app.post("/api/v1/sessions/{session_id}/messages/stream")
def stream_message(
    session_id: str,
    data: UserMessage,
    repository: YobiRepository = Depends(get_repository),
    chat_service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    session, profile = _resolve_session_profile(repository, session_id)
    turn = chat_service.respond(session, profile, data.content)

    def events() -> Any:
        yield "event: message_start\ndata: {}\n\n"
        yield "event: status\ndata: {\"text\":\"Checking menu details…\"}\n\n"
        yield f"event: text_delta\ndata: {json.dumps({'text': turn.text})}\n\n"
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


@app.get("/api/v1/menus/{menu_id}/options")
def get_menu_options(
    menu_id: str, repository: YobiRepository = Depends(get_repository)
) -> list[dict[str, Any]]:
    return [group.model_dump(mode="json") for group in repository.get_options(menu_id)]


@app.get("/api/v1/menus/{menu_id}/evidence")
def get_menu_evidence(
    menu_id: str, repository: YobiRepository = Depends(get_repository)
) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in repository.get_evidence(menu_id)]


def _validate_image(data: bytes, content_type: str | None, max_bytes: int) -> None:
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    _validate_image(data, file.content_type, current_settings.max_upload_mb * 1024 * 1024)
    digest = hashlib.sha256(data).hexdigest()
    filename = (file.filename or "").lower()
    query = "YOBI Myeongdong Hotel" if "yobi" in filename and "booking" in filename else filename
    candidates = repository.resolve_address(query, digest)
    low_confidence = not candidates or candidates[0].confidence < 0.8
    return AddressUploadResult(
        attachment_hash=digest,
        candidates=candidates,
        low_confidence=low_confidence,
        notice=(
            "Canonical demo fallback matched the synthetic booking image metadata. Confirm the address."
            if not low_confidence
            else "OCR confidence is low. Please review or edit the address manually."
        ),
    )


@app.post("/api/v1/sessions/{session_id}/address/confirm")
def confirm_address(
    session_id: str,
    data: AddressConfirm,
    repository: YobiRepository = Depends(get_repository),
) -> dict[str, str]:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    return {"address_ref_id": repository.save_address(session_id, data.candidate)}


@app.get("/api/v1/sessions/{session_id}/cart", response_model=CartPreview)
def get_cart(session_id: str, repository: YobiRepository = Depends(get_repository)) -> CartPreview:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    return repository.get_cart(session_id)


@app.post("/api/v1/sessions/{session_id}/cart/items", response_model=CartPreview)
def add_cart_item(
    session_id: str,
    data: CartItemInput,
    repository: YobiRepository = Depends(get_repository),
) -> CartPreview:
    if not repository.get_session(session_id):
        raise _not_found("SESSION_NOT_FOUND")
    try:
        return repository.add_cart_item(session_id, data)
    except KeyError as exc:
        raise _not_found("MENU_NOT_FOUND") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.patch("/api/v1/sessions/{session_id}/delivery", response_model=CartPreview)
def update_delivery(
    session_id: str,
    data: DeliveryPreferenceInput,
    repository: YobiRepository = Depends(get_repository),
) -> CartPreview:
    try:
        return repository.update_delivery(session_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@app.post("/api/v1/sessions/{session_id}/cart/confirm", response_model=CartPreview)
def confirm_cart(
    session_id: str, repository: YobiRepository = Depends(get_repository)
) -> CartPreview:
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


@app.post("/api/v1/demo/failure-mode", dependencies=[Depends(_demo_authorized)])
def set_failure_mode(
    data: DemoFailureMode, control: DemoControl = Depends(get_demo_control)
) -> dict[str, str]:
    control.set_mode(data.mode)
    return {"mode": data.mode}
