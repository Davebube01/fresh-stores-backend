from pydantic import BaseModel, EmailStr
from typing import Any

class InitializePaymentRequest(BaseModel):
    email: EmailStr
    amount: float
    delivery_fee: float
    delivery_address: str
    order_id: str

class InitializePaymentResponse(BaseModel):
    authorization_url: str
    reference: str
    public_key: str

class PaymentWebhook(BaseModel):
    event: str
    data: dict[str, Any]

class PaymentWebhookSimulate(BaseModel):
    reference: str

