import logging

import uvicorn

from app.api import create_app
from app.config import Settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

settings = Settings()
app = create_app(settings)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
