"""Pydantic schemas for the experimental WhatsApp assistant (Phase 23) --
both the organization-facing Settings -> WhatsApp REST surface
(app.routers.whatsapp) and the bridge's inbound envelope
(app.routers.whatsapp_bridge). Kept in this package rather than
app/schemas.py since these are specific to one experimental feature, not
core domain schemas every router already imports from one shared file.
"""

from typing import Literal

from pydantic import BaseModel, Field


class WhatsAppInboundMedia(BaseModel):
    mime_type: str
    size_bytes: int = Field(ge=0)
    # Base64-encoded raw bytes -- the bridge downloads the media from
    # WhatsApp itself and forwards it here; this app never fetches media
    # from WhatsApp directly. Validated for size/MIME BEFORE decoding (see
    # app.whatsapp.service) so an oversized declared size_bytes is
    # rejected without ever base64-decoding a huge string into memory.
    content_base64: str = ""


class WhatsAppInboundEnvelope(BaseModel):
    """The normalized inbound message shape every provider adapter in the
    Node bridge must produce (see whatsapp-bridge/src/transport/
    inbound-handler.ts) before it's posted to
    POST /whatsapp/bridge/inbound. `provider` is echoed back on every
    outbound instruction so a future second transport (Meta Cloud API)
    can coexist without this backend ever guessing which one is live."""

    provider: str = Field(min_length=1, max_length=32)
    message_id: str = Field(min_length=1, max_length=128)
    phone_number: str = Field(min_length=1, max_length=64)
    timestamp: str
    type: Literal["text", "audio"]
    text: str = Field(default="", max_length=4096)
    media: WhatsAppInboundMedia | None = None


class WhatsAppQuotaResponse(BaseModel):
    used: int
    limit: int | None
    unlimited: bool


class WhatsAppConnectionResponse(BaseModel):
    state: str
    connected_phone_number: str | None
    last_heartbeat_at: str | None


class WhatsAppStatusResponse(BaseModel):
    """GET .../whatsapp/status -- deliberately distinguishes three
    independent reasons the feature might not be usable right now
    (transport disabled, transport enabled-but-unconfigured, plan
    doesn't include it), per docs/whatsapp.md's "Plans and quotas"
    section, rather than collapsing them into one boolean."""

    transport_enabled: bool
    transport_configured: bool
    plan_allows_whatsapp: bool
    plan_allows_voice_messages: bool
    connection: WhatsAppConnectionResponse
    whatsapp_users_quota: WhatsAppQuotaResponse
    whatsapp_actions_quota: WhatsAppQuotaResponse


class WhatsAppQrResponse(BaseModel):
    qr_data_base64: str
    expires_at: str


class WhatsAppLinkRequest(BaseModel):
    phone_number: str = Field(min_length=3, max_length=32)


class WhatsAppLinkResponse(BaseModel):
    """The one and only time the raw verification code is ever exposed --
    never persisted anywhere beyond its hash (see WhatsAppIdentity
    .verification_code_hash), never logged."""

    identity_id: str
    normalized_phone_number: str
    status: str
    verification_code: str
    verification_expires_at: str


class WhatsAppIdentityResponse(BaseModel):
    id: str
    user_id: str
    user_email: str
    normalized_phone_number: str
    status: str
    verified_at: str | None
    last_message_at: str | None
    created_at: str


class WhatsAppIdentityListResponse(BaseModel):
    items: list[WhatsAppIdentityResponse]


class WhatsAppCommandHistoryItemResponse(BaseModel):
    """Safe metadata only -- see WhatsAppInboundMessage's own docstring
    for why raw message/transcript text is never included here."""

    id: str
    message_type: str
    command_action: str | None
    status: str
    failure_code: str | None
    created_at: str


class WhatsAppCommandHistoryResponse(BaseModel):
    items: list[WhatsAppCommandHistoryItemResponse]
