from fastapi import FastAPI

from app.api.routes import router
from app.db.base import Base
from app.db.session import engine
from app.models import document  # noqa: F401


app = FastAPI(title="CompliTrace Ingestion Service", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


app.include_router(router)
