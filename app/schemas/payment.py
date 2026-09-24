from pydantic import BaseModel, EmailStr
from typing import Any

class InitializePaymentRequest(BaseModel):
    email: EmailStr
    order_id: str
    # No amount field on purpose: the amount charged is always the order's
    # own total_amount, looked up server-side — never trust a client-sent
    # figure for what to charge.

class InitializePaymentResponse(BaseModel):
    authorization_url: str
    reference: str
    public_key: str

class PaymentWebhook(BaseModel):
    event: str
    data: dict[str, Any]

class PaymentWebhookSimulate(BaseModel):
    reference: str

