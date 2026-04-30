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
