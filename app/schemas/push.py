from pydantic import BaseModel


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    """Shape of the browser's PushSubscription.toJSON()."""
    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


class VapidPublicKeyResponse(BaseModel):
    public_key: str | None
