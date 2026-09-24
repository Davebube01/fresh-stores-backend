import uvicorn
import os
from app.main import app

if __name__ == "__main__":
    # This matches the user's requested deployment command: uvicorn main:app
    port = int(os.environ.get("PORT", 8000))
    # Behind a reverse proxy (Render, nginx, ...) every request arrives from the
    # proxy's IP; uvicorn only reads the real client IP from X-Forwarded-For
    # when the proxy is trusted. Without this, all users share ONE IP and hit
    # the per-IP rate limits together. Trusted by default in production only;
    # override with FORWARDED_ALLOW_IPS (comma-separated IPs, or "*").
    trusted = os.environ.get(
        "FORWARDED_ALLOW_IPS",
        "*" if os.environ.get("ENV") == "production" else "127.0.0.1",
    )
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips=trusted,
    )
