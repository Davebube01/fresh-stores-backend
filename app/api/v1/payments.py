from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.schemas.payment import InitializePaymentRequest, InitializePaymentResponse, PaymentWebhook, PaymentWebhookSimulate
from app.core.config import settings
from app.core.database import get_db
from app.core.payment_window import payment_deadline
from app.crud.order import UNPAID_STATUSES, cancel_order
from app.models.user import User
from app.utils.dependencies import get_optional_current_user
from app.models.order import Order, OrderStatus
from pypaystack2 import AsyncPaystackClient

router = APIRouter()
logger = logging.getLogger("payments")

@router.post("/initialize", response_model=InitializePaymentResponse)
async def initialize_payment(
    payment_in: InitializePaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    """
    Start (or retry) a Paystack payment for an order that's still awaiting
    payment. Safe to call more than once: each call issues a fresh reference,
    and a payment made with an earlier reference is still matched to the
    order by the webhook (see process_successful_payment).
    """
    result = await db.execute(select(Order).where(Order.id == payment_in.order_id))
    order = result.scalar_one_or_none()

    # Orders that belong to an account can only be paid from that account.
    # Same answer as "doesn't exist" so ids can't be probed. Guest orders
    # (no user) stay payable by id, as before.
    if not order or (order.user_id and (not current_user or current_user.id != order.user_id)):
        raise HTTPException(status_code=404, detail="Order not found")

    status = getattr(order.status, "value", order.status)
    if status == "cancelled":
        raise HTTPException(status_code=400, detail="This order has been cancelled, so it can't be paid.")
    if status not in UNPAID_STATUSES:
        raise HTTPException(status_code=400, detail="This order has already been paid for.")
    if order.payment_method == "cod":
        raise HTTPException(status_code=400, detail="This order is pay-on-delivery, so there's nothing to pay online.")
    if order.total_amount <= 0:
        raise HTTPException(status_code=400, detail="Order has nothing to charge")

    # Past its payment window but not yet swept: close it now (releasing its
    # stock) rather than take money for an order that's about to be cancelled.
    deadline = payment_deadline(order.status, order.payment_method, order.created_at, order.updated_at)
    if deadline and deadline <= datetime.now(timezone.utc):
        try:
            await cancel_order(db, order.id, "Payment not completed", "system", allowed_from=list(UNPAID_STATUSES))
        except ValueError:
            pass  # someone else changed it first; the caller sees the new state on retry
        raise HTTPException(
            status_code=400,
            detail="The time to pay for this order has run out, so it was cancelled. Please place a new order.",
        )

    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Payment gateway not configured")

    # Fresh reference per attempt. The previous one is kept until Paystack
    # accepts the new one: a failed retry must not wipe a reference the
    # customer may still be paying with in another tab.
    previous_reference = order.payment_reference
    payment_reference = f"GOAT-{uuid.uuid4()}"
    order.payment_reference = payment_reference
    await db.commit()

    paystack = AsyncPaystackClient(secret_key=settings.PAYSTACK_SECRET_KEY)

    # Always charge the order's own server-computed total, never a
    # client-supplied amount, which would let a request simply name its own
    # price.
    amount_in_kobo = int(order.total_amount * 100)

    try:
        response = await paystack.transactions.initialize(
            email=payment_in.email,
            amount=amount_in_kobo,
            reference=payment_reference,
            metadata={"order_id": str(order.id)},
        )
    except Exception:
        logger.exception("Paystack initialize failed for order %s", order.id)
        order.payment_reference = previous_reference
        await db.commit()
        raise HTTPException(status_code=502, detail="We couldn't reach the payment provider. Please try again.")

    if not response.status:
        order.payment_reference = previous_reference
        await db.commit()
        raise HTTPException(status_code=400, detail=f"Paystack error: {response.message}")

    return InitializePaymentResponse(
        authorization_url=response.data.authorization_url,
        reference=response.data.reference,
        public_key=settings.PAYSTACK_PUBLIC_KEY or ""
    )


def verify_paystack_signature(raw_body: bytes, signature: str | None) -> bool:
    """Paystack signs every webhook with HMAC-SHA512 of the raw body, keyed by our secret key."""
    if not settings.PAYSTACK_SECRET_KEY or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def simulator_allowed() -> bool:
    """
    The dev-only "pretend Paystack paid" shortcut. Never in production, and
    never with a live key, so a server whose ENV was left unset can't be
    talked into marking real orders paid.
    """
    return settings.ENV != "production" and not (settings.PAYSTACK_SECRET_KEY or "").startswith("sk_live_")


@router.post("/webhook")
async def paystack_webhook(
    request: Request,
    webhook_data: PaymentWebhook,
    x_paystack_signature: str | None = Header(None, alias="x-paystack-signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    Called by Paystack. The signature is checked in every environment: an
    unsigned or wrongly signed call is refused, whatever ENV says. (Locally,
    use /webhook/simulate instead; Paystack can't reach localhost anyway.)
    """
    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")
    if not verify_paystack_signature(await request.body(), x_paystack_signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

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
    Local development only: behave as if Paystack confirmed payment of the
    order with this reference, for its full amount (so it goes through the
    same checks as a real payment).
    """
    if not simulator_allowed():
        raise HTTPException(status_code=403, detail="Payment simulation is only available in development with test keys")

    order = (await db.execute(select(Order).where(Order.payment_reference == payload.reference))).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="No order has this payment reference")
    await process_successful_payment(
        payload.reference,
        {"simulated": True, "reference": payload.reference, "currency": "NGN", "amount": _kobo(order.total_amount)},
        db,
    )
    return {"status": "success", "message": f"Payment simulated for {payload.reference}"}


def _kobo(naira: float | None) -> int:
    return int(round(float(naira or 0) * 100))


def amount_problem(order: Order, gateway_response: dict) -> str | None:
    """Why this charge can't pay for this order, or None if it covers it."""
    data = gateway_response or {}
    currency = data.get("currency")
    if currency is not None and str(currency).upper() != "NGN":
        return f"paid in {currency}, expected NGN"
    try:
        paid = int(data.get("amount"))
    except (TypeError, ValueError):
        return "no amount in the payment confirmation"
    expected = _kobo(order.total_amount)
    if paid < expected:
        return f"paid {paid} kobo, order total is {expected} kobo"
    return None


def _metadata_order_id(gateway_response: dict) -> str | None:
    metadata = (gateway_response or {}).get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return None
    if isinstance(metadata, dict) and metadata.get("order_id"):
        return str(metadata["order_id"])
    return None


async def process_successful_payment(reference: str, gateway_response: dict, db: AsyncSession):
    """
    Records a successful charge against its order.

    The order is found by reference first, then by the order_id we attach to
    every transaction as metadata. The fallback matters because a retry issues
    a new reference and overwrites the stored one: a payment completed with
    the *earlier* reference would otherwise match nothing and be lost.
    """
    result = await db.execute(select(Order.id).where(Order.payment_reference == reference))
    order_id = result.scalar_one_or_none()
    if order_id is None:
        order_id = _metadata_order_id(gateway_response)
    if order_id is None:
        logger.warning("Successful payment %s matched no order", reference)
        return

    # The amount must cover the order: a charge for less (or in another
    # currency) is kept as evidence on the order but never marks it paid.
    order = (await db.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        return
    problem = amount_problem(order, gateway_response)
    if problem:
        recorded = dict(order.payment_gateway_response or {})
        rejected = list(recorded.get("rejected_payments", []))
        if not any(r.get("reference") == reference for r in rejected):
            rejected.append({
                "reference": reference,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "amount": (gateway_response or {}).get("amount"),
                "currency": (gateway_response or {}).get("currency"),
                "reason": problem,
            })
            recorded["rejected_payments"] = rejected
            order.payment_gateway_response = recorded
            await db.commit()
        logger.error("PAYMENT NOT APPLIED to order %s (reference %s): %s - check and refund", order_id, reference, problem)
        return

    # One conditional UPDATE, so a payment and a cancellation racing each
    # other can't overwrite one another: whichever lands first wins. The
    # reference that actually paid becomes the order's payment_reference.
    now = datetime.now(timezone.utc)
    updated = await db.execute(
        update(Order)
        .where(
            Order.id == order_id,
            Order.status.in_([OrderStatus.PENDING, OrderStatus.AWAITING_VERIFICATION]),
        )
        .values(
            status=OrderStatus.PROCESSING,
            paid_at=now,
            payment_reference=reference,
            payment_gateway_response=gateway_response,
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount:
        await db.commit()
        return

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order is None:
        return

    # Cancelled before the money arrived (e.g. it timed out while the
    # customer was paying): the payment is real but the order is dead. Keep
    # the evidence and flag it for a refund instead of silently dropping it.
    if order.status == OrderStatus.CANCELLED and order.paid_at is None:
        order.paid_at = now
        order.payment_reference = reference
        order.payment_gateway_response = gateway_response
        await db.commit()
        logger.warning("PAYMENT RECEIVED FOR CANCELLED ORDER %s (reference %s) - refund needed", order.id, reference)
        return

    # Already paid, and this is a *different* reference: the customer paid
    # twice (e.g. retried while a first payment was still confirming).
    # The same reference again is just Paystack re-delivering the webhook.
    if order.paid_at is not None and order.payment_reference != reference:
        recorded = dict(order.payment_gateway_response or {})
        extra = list(recorded.get("extra_payments", []))
        if not any(e.get("reference") == reference for e in extra):
            extra.append({
                "reference": reference,
                "received_at": now.isoformat(),
                "amount": (gateway_response or {}).get("amount"),
            })
            recorded["extra_payments"] = extra
            order.payment_gateway_response = recorded
            await db.commit()
            logger.error(
                "DUPLICATE PAYMENT for order %s (reference %s; order was already paid with %s) - refund needed",
                order.id, reference, order.payment_reference,
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
