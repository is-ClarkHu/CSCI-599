import logging

import uvicorn

from app.api import create_app
from app.config import Settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx/httpcore log every request URL at INFO; keep them quiet so no URL ever reaches Cloud Run logs.
for noisy in ("httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

settings = Settings()
app = create_app(settings)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
