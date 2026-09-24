import logging
from typing import Dict, Any

# Configure a secure local logger to simulate email output streams
logger = logging.getLogger("email_service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('[EMAIL MOCK SERVER] %(message)s'))
if not logger.handlers:
    logger.addHandler(handler)

async def send_order_confirmation(email: str, order_id: str, total_amount: float, tracking_url: str) -> None:
    """
    Simulates sending a post-purchase confirmation email with tracking capability.
    To be run as a FastAPI Background Task during checkout.
    """
    
    # In the future, plugin SendGrid, Anymail, or fastapi-mail here using os.getenv() hooks.
    
    email_body = f"""
    ========================================================
    To: {email}
    Subject: Order Confirmation #{order_id} - Meat Store
    ========================================================
    Hello!
    
    Thank you for your order. We’ve securely received your request and 
    are preparing it for processing!
    
    Order Summary:
    --------------------------
    Order ID: {order_id}
    Total Paid: ₦{total_amount:,.2f}
    
    >> TRACK YOUR ORDER LIVE: 
    {tracking_url}
    
    (Note: If tracking as a guest, please use the email address this was sent to alongside your Order ID to authenticate).
    
    Best Returns,
    The Support Team
    ========================================================
    """
    
    # Output the dispatched message locally for verification
    logger.info(f"Delivering Order Confirmation to {email}:\n{email_body}")


async def send_verification_email(email: str, full_name: str | None, verify_url: str) -> None:
    """
    Simulated for now (logs the message, including the link, to the backend
    console). Swap the body for a real provider (Resend, Brevo, ...) when one
    is chosen — callers already run this as a background task.
    """
    greeting = f"Hi {full_name}," if full_name else "Hi,"
    email_body = f"""
    ========================================================
    To: {email}
    Subject: Confirm your email address - Meat Store
    ========================================================
    {greeting}

    Welcome to Meat Store! Please confirm this email address so we can
    keep your account secure and link any earlier orders to it.

    >> CONFIRM YOUR EMAIL:
    {verify_url}

    This link expires in 48 hours. If you didn't create an account,
    you can ignore this email.

    The Support Team
    ========================================================
    """
    logger.info(f"Delivering verification email to {email}:\n{email_body}")
