import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def test_payment_flow():
    print("Starting Payment Integration Test...")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Create an order via /api/v1/orders/checkout
        print("\nTesting /api/v1/orders/checkout to create an order...")
        checkout_payload = {
            "is_guest": True,
            "guest_info": {"fullName": "Test User", "email": "test@example.com", "phone": "08012345678"},
            "delivery_info": {
                "address": "123 Test St", "city": "Lagos", "state": "Lagos", 
                "deliveryZone": "Island", "deliveryFee": 1500.0
            },
            "payment_method": "paystack",
            "items": []  # Empty items list just for testing if the backend allows it
        }
        
        checkout_res = await client.post("/api/v1/orders/checkout", json=checkout_payload)
        
        if checkout_res.status_code != 200:
            print(f"Checkout failed: {checkout_res.status_code} - {checkout_res.text}")
            print("Since we can't create an order automatically via HTTP (might require valid products), you can also run the test manually as described in the walkthrough.")
            return
            
        order_data = checkout_res.json()
        order_id = order_data["id"]
        total_amount = order_data["total_amount"]
        print(f"Created order successfully! ID: {order_id}, Total: {total_amount}")

        # 2. Test Payment Initialization
        print("\nTesting /api/v1/payments/initialize...")
        init_payload = {
            "email": "test@example.com",
            "amount": total_amount,
            "delivery_fee": 1500.0,
            "delivery_address": "123 Test St",
            "order_id": order_id
        }
        
        init_res = await client.post("/api/v1/payments/initialize", json=init_payload)
        
        if init_res.status_code == 200:
            data = init_res.json()
            reference = data["reference"]
            print(f"Initialization successful! Reference: {reference}")
            print(f"Auth URL: {data['authorization_url']}")
        else:
            print(f"Initialization failed: {init_res.status_code} - {init_res.text}")
            print("Make sure you have a valid PAYSTACK_SECRET_KEY in your .env file!")
            return

        # 3. Simulate Webhook (Simulates a successful payment)
        print("\nSimulating webhook from Paystack...")
        webhook_payload = {
            "reference": reference
        }
        webhook_res = await client.post("/api/v1/payments/webhook/simulate", json=webhook_payload)
        
        if webhook_res.status_code == 200:
            print("Webhook simulation successful!")
        else:
            print(f"Webhook simulation failed: {webhook_res.status_code} - {webhook_res.text}")
            return

        # 4. Verify the order status changed in the DB
        print("\nVerifying order status...")
        order_res = await client.get(f"/api/v1/orders/{order_id}")
        if order_res.status_code == 200:
            final_order = order_res.json()
            if final_order["status"] == "processing":
                print(f"Order status successfully updated to: PROCESSING")
                print(f"Paid at: {final_order.get('paid_at')}")
            else:
                print(f"Order status didn't update properly. Current status: {final_order['status']}")
        else:
            print("Failed to fetch order to verify status.")

if __name__ == "__main__":
    asyncio.run(test_payment_flow())
