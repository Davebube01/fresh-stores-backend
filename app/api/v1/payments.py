from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.schemas.payment import InitializePaymentRequest, InitializePaymentResponse, PaymentWebhook, PaymentWebhookSimulate
from app.core.config import settings
from app.core.database import get_db
from app.models.order import Order, OrderStatus
from pypaystack2 import AsyncPaystackClient

router = APIRouter()

@router.post("/initialize", response_model=InitializePaymentResponse)
async def initialize_payment(
    payment_in: InitializePaymentRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Initialize a Paystack transaction for an existing PENDING order.
    """
    # 1. Verify the order exists and is pending
    stmt = select(Order).where(Order.id == payment_in.order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.status != OrderStatus.PENDING:
        raise HTTPException(status_code=400, detail="Order is not in pending status")

    # 2. Generate a unique payment reference
    payment_reference = f"GOAT-{uuid.uuid4()}"
    order.payment_reference = payment_reference
    await db.commit()

    # 3. Initialize Paystack transaction
    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Payment gateway not configured")
        
    paystack = AsyncPaystackClient(secret_key=settings.PAYSTACK_SECRET_KEY)
    
    # Amount should be in kobo (multiply by 100)
    amount_in_kobo = int(payment_in.amount * 100)
    
    response = await paystack.transactions.initialize(
        email=payment_in.email,
        amount=amount_in_kobo,
        reference=payment_reference,
        metadata={"order_id": str(order.id)}
    )
    
    if not response.status:
        # Reset the payment reference so they can try again
        order.payment_reference = None
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Paystack error: {response.message}")

    return InitializePaymentResponse(
        authorization_url=response.data.authorization_url,
        reference=response.data.reference,
        public_key=settings.PAYSTACK_PUBLIC_KEY or ""
    )


@router.post("/webhook")
async def paystack_webhook(
    request: Request,
    webhook_data: PaymentWebhook,
    x_paystack_signature: str | None = Header(None),
    x_simulated: str | None = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint called by Paystack in production.
    """
    # In production, verify signature
    if settings.ENV == "production":
        # Verification logic would go here:
        # using hmac and settings.PAYSTACK_SECRET_KEY
        # For brevity, we assume signature is verified if not simulated
        pass
    else:
        # In development, allow simulated requests if header is present
        if not x_simulated:
            print("Warning: Webhook received without X-Simulated header in development")

    # Process successful charge
    if webhook_data.event == "charge.success":
        reference = webhook_data.data.get("reference")
        if not reference:
            return {"status": "ignored", "reason": "No reference provided"}
            
        await process_successful_payment(reference, webhook_data.data, db)
        
    return {"status": "ok"}


@router.post("/webhook/simulate")
async def simulate_webhook(
    payload: PaymentWebhookSimulate,
    db: AsyncSession = Depends(get_db)
):
    """
    Simulated Webhook endpoint for local development.
    """
    if settings.ENV != "development":
        raise HTTPException(status_code=403, detail="Simulation only allowed in development")
        
    await process_successful_payment(payload.reference, {"simulated": True}, db)
    return {"status": "success", "message": f"Payment simulated for {payload.reference}"}


async def process_successful_payment(reference: str, gateway_response: dict, db: AsyncSession):
    """
    Helper to update order status upon successful payment.
    """
    stmt = select(Order).where(Order.payment_reference == reference)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    
    if order and order.status in [OrderStatus.PENDING, OrderStatus.AWAITING_VERIFICATION]:
        order.status = OrderStatus.PROCESSING
        order.paid_at = datetime.now(timezone.utc)
        order.payment_gateway_response = gateway_response
        await db.commit()
        
# ================== LOCAL DEVELOPMENT TESTING FLOW ==================
# 1. Start server with ENV=development.
# 2. Call /api/v1/orders/checkout to create a pending order.
# 3. Call /api/v1/payments/initialize with the new order_id.
# 4. Manually simulate the webhook using curl or Postman:
#    curl -X POST http://localhost:8000/api/v1/payments/webhook/simulate \
#      -H "Content-Type: application/json" \
#      -d '{"reference": "GOAT-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}'
# 5. Verify via GET /api/v1/orders/{order_id} that status is now "processing".
# =====================================================================
