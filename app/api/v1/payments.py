from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

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

    if order.total_amount <= 0:
        raise HTTPException(status_code=400, detail="Order has nothing to charge")

    # 2. Generate a unique payment reference
    payment_reference = f"GOAT-{uuid.uuid4()}"
    order.payment_reference = payment_reference
    await db.commit()

    # 3. Initialize Paystack transaction
    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Payment gateway not configured")

    paystack = AsyncPaystackClient(secret_key=settings.PAYSTACK_SECRET_KEY)

    # Always charge the order's own server-computed total — never a
    # client-supplied amount, which would let a request simply name its own
    # price.
    amount_in_kobo = int(order.total_amount * 100)
    
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
    x_paystack_signature: str | None = Header(None, alias="x-paystack-signature"),
    x_simulated: str | None = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook endpoint called by Paystack in production.
    """
    if settings.ENV == "production":
        if not settings.PAYSTACK_SECRET_KEY:
            raise HTTPException(status_code=500, detail="Payment gateway not configured")

        raw_body = await request.body()
        expected_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        if not x_paystack_signature or not hmac.compare_digest(expected_signature, x_paystack_signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
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
    # One conditional UPDATE, so a payment and a cancellation racing each
    # other can't overwrite one another: whichever lands first wins.
    now = datetime.now(timezone.utc)
    updated = await db.execute(
        update(Order)
        .where(
            Order.payment_reference == reference,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.AWAITING_VERIFICATION]),
        )
        .values(status=OrderStatus.PROCESSING, paid_at=now, payment_gateway_response=gateway_response)
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount:
        await db.commit()
        return

    # Not moved to processing. If that's because the order was already
    # cancelled (e.g. the customer paid just as it timed out), the money is
    # real but the order is dead — keep the evidence and flag it for a refund
    # instead of silently dropping the payment.
    result = await db.execute(select(Order).where(Order.payment_reference == reference))
    order = result.scalar_one_or_none()
    if order and order.status == OrderStatus.CANCELLED and order.paid_at is None:
        order.paid_at = now
        order.payment_gateway_response = gateway_response
        await db.commit()
        logging.getLogger("payments").warning(
            "PAYMENT RECEIVED FOR CANCELLED ORDER %s (reference %s) - refund needed", order.id, reference
        )
        
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
