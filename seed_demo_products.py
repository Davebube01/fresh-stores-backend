"""
One-off local dev seed script: clears nothing (products already cleared),
generates a placeholder image per product, uploads each through the real
/admin/upload -> Cloudinary pipeline, then creates the product.

Run against a local backend only. Not part of the app itself — delete this
file once you're done looking at the seeded catalog, or leave it as a handy
reset script for local dev.
"""
import io
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@meatstore.com"
ADMIN_PASSWORD = "adminpassword123"

try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 42)
    FONT_SMALL = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
except OSError:
    FONT = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()

CATEGORY_COLORS = {
    "goat-meat": ("#5C2E22", "#F2E4DE"),
    "goat-parts": ("#8A4B33", "#F5E8DE"),
    "per-kg": ("#946B1F", "#F6EEDB"),
    "bundles": ("#2F5233", "#E4EBE0"),
    "vegetables": ("#3F7A3F", "#E7F2E3"),
}

PRODUCTS = [
    {"name": "Whole Goat (Processed)", "category": "goat-meat", "price": 85000,
     "weight_options": ["Full"], "stock_quantity": 6,
     "description": "A whole processed goat, cleaned and ready for cooking."},
    {"name": "Goat Leg", "category": "per-kg", "price": 8500,
     "weight_options": ["1kg", "2kg"], "stock_quantity": 24,
     "description": "Fresh goat leg cuts, sold by weight."},
    {"name": "Goat Shoulder", "category": "per-kg", "price": 7500,
     "weight_options": ["1kg", "2kg"], "stock_quantity": 18,
     "description": "Tender goat shoulder, great for slow cooking."},
    {"name": "Goat Ribs", "category": "goat-parts", "price": 6000,
     "weight_options": ["1kg"], "stock_quantity": 15,
     "description": "Bone-in goat ribs, a peppersoup favorite."},
    {"name": "Goat Head", "category": "goat-parts", "price": 4500,
     "weight_options": ["1 piece"], "stock_quantity": 8,
     "description": "Cleaned goat head, ready for the pot."},
    {"name": "Goat Liver", "category": "goat-parts", "price": 3500,
     "weight_options": ["500g"], "stock_quantity": 12,
     "description": "Fresh goat liver."},
    {"name": "Goat Intestines (Shaki)", "category": "goat-parts", "price": 3000,
     "weight_options": ["500g"], "stock_quantity": 10,
     "description": "Cleaned goat intestines, ready to cook."},
    {"name": "Family Bundle (Mixed Cuts)", "category": "bundles", "price": 15000,
     "weight_options": ["3kg mix"], "stock_quantity": 9,
     "description": "A mixed bundle of goat cuts — leg, ribs, and shoulder — sized for a family meal."},
    {"name": "Party Pack (5kg Mixed)", "category": "bundles", "price": 35000,
     "weight_options": ["5kg mix"], "stock_quantity": 4,
     "description": "A large mixed bundle for parties and gatherings."},
    {"name": "Fresh Tomatoes", "category": "vegetables", "price": 1500,
     "weight_options": ["1kg"], "stock_quantity": 40,
     "description": "Fresh, ripe tomatoes."},
    {"name": "Pepper Mix (Tatashe & Rodo)", "category": "vegetables", "price": 1200,
     "weight_options": ["500g"], "stock_quantity": 35,
     "description": "A fresh mix of bell and scotch bonnet peppers."},
    {"name": "Fresh Onions", "category": "vegetables", "price": 1000,
     "weight_options": ["1kg"], "stock_quantity": 3,
     "description": "Fresh onions, sold by weight."},
]


def make_image(name: str, category: str) -> bytes:
    bg, fg = CATEGORY_COLORS.get(category, ("#444444", "#EEEEEE"))
    img = Image.new("RGB", (800, 800), bg)
    draw = ImageDraw.Draw(img)

    draw.ellipse((80, 80, 720, 720), fill=fg)

    words = name.split()
    lines, current = [], ""
    for w in words:
        trial = (current + " " + w).strip()
        if draw.textlength(trial, font=FONT) > 560:
            lines.append(current)
            current = w
        else:
            current = trial
    lines.append(current)

    total_h = len(lines) * 54
    y = 400 - total_h // 2
    for line in lines:
        w = draw.textlength(line, font=FONT)
        draw.text((400 - w / 2, y), line, fill=bg, font=FONT)
        y += 54

    label = category.replace("-", " ").upper()
    w = draw.textlength(label, font=FONT_SMALL)
    draw.text((400 - w / 2, 620), label, fill=bg, font=FONT_SMALL)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def main():
    resp = requests.post(f"{BASE_URL}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    resp.raise_for_status()
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    for p in PRODUCTS:
        img_bytes = make_image(p["name"], p["category"])
        files = {"file": (f"{p['name']}.jpg", img_bytes, "image/jpeg")}
        up = requests.post(f"{BASE_URL}/admin/upload", headers=headers, files=files)
        up.raise_for_status()
        image_url = up.json()["imageUrl"]

        slug = p["name"].lower().replace("(", "").replace(")", "").replace("&", "and")
        slug = "-".join(slug.split())

        payload = {
            "name": p["name"],
            "slug": slug,
            "price": p["price"],
            "description": p["description"],
            "image_url": image_url,
            "category": p["category"],
            "weight_options": p["weight_options"],
            "stock_quantity": p["stock_quantity"],
            "is_active": True,
        }
        create = requests.post(f"{BASE_URL}/admin/products", headers=headers, json=payload)
        create.raise_for_status()
        print(f"created: {p['name']}  ->  {image_url}")

    print("\nDone.")


if __name__ == "__main__":
    main()
