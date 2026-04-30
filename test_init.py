import sqlite3
import urllib.request
import json

db_path = "sql_app.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT id FROM orders WHERE status='pending' LIMIT 1")
row = cursor.fetchone()

if row:
    order_id = row[0]
    print(f"Found pending order: {order_id}")
    
    data = json.dumps({
        "email": "test@example.com",
        "amount": 15000,
        "delivery_fee": 1000,
        "delivery_address": "12 Goat Street, Abuja",
        "order_id": order_id
    }).encode('utf-8')
    
    req = urllib.request.Request("http://127.0.0.1:8000/api/v1/payments/initialize", data=data, headers={'Content-Type': 'application/json'})
    
    try:
        with urllib.request.urlopen(req) as response:
            print("Response:", response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.read().decode('utf-8')}")
else:
    print("No pending orders found.")
