import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_checkout_validation(client: AsyncClient):
    response = await client.post(
        "/api/v1/orders/checkout",
        json={
            "is_guest": True,
            "guest_info": {"fullName": "Guest", "email": "guest@test.com", "phone": "123"},
            "payment_method": "cod",
            "items": []
        }
    )
    # Fails because no items
    assert response.status_code == 400
    assert response.json()["detail"] == "No items provided for checkout"
