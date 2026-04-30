import uvicorn
import os
from app.main import app

if __name__ == "__main__":
    # This matches the user's requested deployment command: uvicorn main:app
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
