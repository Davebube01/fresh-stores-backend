"""
One-off local dev script: replaces the placeholder product images with real
photos sourced from Wikimedia Commons (all CC-licensed or public domain, see
ATTRIBUTIONS below), uploaded through the real /admin/upload -> Cloudinary
pipeline, then PUTs each product's image_url.
"""
import requests

BASE_URL = "http://127.0.0.1:8000"
ADMIN_EMAIL = "admin@meatstore.com"
ADMIN_PASSWORD = "adminpassword123"

WIKIMEDIA_FILES = {
    "goat_half": "A_Goat_cut_in_half.jpg",
    "goat_legs": "Goat_legs_for_sale.JPG",
    "goat_meat": "Goat_meat.jpg",
    "goat_tripe_heads": "Goat_tripe_and_heads_at_Peru_market.jpg",
    "goat_frozen": "Frozen_goat_meat_for_sale_at_Lucky.jpg",
    "tomatoes": "Fresh_big_juicy_tomatoes.jpg",
    "pepper": "Scotch_bonnet_chili_pepper.jpg",
    "onions": "YellowOnions.jpg",
}

# slug -> which wikimedia file to use
PRODUCT_IMAGE = {
    "whole-goat-processed": "goat_half",
    "goat-leg": "goat_legs",
    "goat-shoulder": "goat_meat",
    "goat-ribs": "goat_meat",
    "goat-head": "goat_tripe_heads",
    "goat-liver": "goat_frozen",
    "goat-intestines-shaki": "goat_tripe_heads",
    "family-bundle-mixed-cuts": "goat_frozen",
    "party-pack-5kg-mixed": "goat_frozen",
    "fresh-tomatoes": "tomatoes",
    "pepper-mix-tatashe-and-rodo": "pepper",
    "fresh-onions": "onions",
}


def download_wikimedia(filename: str) -> bytes:
    url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}"
    r = requests.get(url, headers={"User-Agent": "meat-store-dev-seed/1.0"}, allow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.content


def main():
    resp = requests.post(f"{BASE_URL}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    resp.raise_for_status()
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    print("Downloading source images from Wikimedia Commons...")
    cloudinary_urls = {}
    for key, filename in WIKIMEDIA_FILES.items():
        content = download_wikimedia(filename)
        ext = "png" if filename.lower().endswith(".png") else "jpg"
        files = {"file": (f"{key}.{ext}", content, "image/jpeg")}
        up = requests.post(f"{BASE_URL}/admin/upload", headers=headers, files=files)
        up.raise_for_status()
        cloudinary_urls[key] = up.json()["imageUrl"]
        print(f"  {filename} -> {cloudinary_urls[key]}")

    print("\nUpdating products...")
    products = requests.get(f"{BASE_URL}/admin/products", headers=headers).json()
    by_slug = {p["slug"]: p for p in products}

    for slug, image_key in PRODUCT_IMAGE.items():
        product = by_slug.get(slug)
        if not product:
            print(f"  SKIP (not found): {slug}")
            continue
        new_url = cloudinary_urls[image_key]
        update = requests.put(
            f"{BASE_URL}/admin/products/{product['id']}",
            headers=headers,
            json={"image_url": new_url},
        )
        update.raise_for_status()
        print(f"  updated {product['name']}")

    print("\nDone.")


if __name__ == "__main__":
    main()
