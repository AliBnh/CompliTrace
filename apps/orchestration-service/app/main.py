import json
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import inspect, text
from starlette.responses import Response

from app.api.routes import router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


class _JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "service": self._service,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    root = logging.getLogger()
    formatter = _JsonFormatter(service="orchestration-service")
    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(formatter)
    else:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    root.setLevel(logging.INFO)


_configure_logging()


app = FastAPI(title="CompliTrace Orchestration Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_findings_columns()


def _ensure_findings_columns() -> None:
    with engine.begin() as conn:
        inspector = inspect(conn)
        if "findings" not in inspector.get_table_names():
            return
        columns = {col["name"] for col in inspector.get_columns("findings")}
        column_ddls = {
            "classification": "ALTER TABLE findings ADD COLUMN classification VARCHAR(32)",
            "confidence": "ALTER TABLE findings ADD COLUMN confidence DOUBLE PRECISION",
            "confidence_evidence": "ALTER TABLE findings ADD COLUMN confidence_evidence DOUBLE PRECISION",
            "confidence_applicability": "ALTER TABLE findings ADD COLUMN confidence_applicability DOUBLE PRECISION",
            "confidence_article_fit": "ALTER TABLE findings ADD COLUMN confidence_article_fit DOUBLE PRECISION",
            "confidence_synthesis": "ALTER TABLE findings ADD COLUMN confidence_synthesis DOUBLE PRECISION",
            "confidence_overall": "ALTER TABLE findings ADD COLUMN confidence_overall DOUBLE PRECISION",
            "finding_type": "ALTER TABLE findings ADD COLUMN finding_type VARCHAR(32) DEFAULT 'local'",
            "publish_flag": "ALTER TABLE findings ADD COLUMN publish_flag VARCHAR(8) DEFAULT 'yes'",
            "missing_from_section": "ALTER TABLE findings ADD COLUMN missing_from_section VARCHAR(8)",
            "missing_from_document": "ALTER TABLE findings ADD COLUMN missing_from_document VARCHAR(8)",
            "not_visible_in_excerpt": "ALTER TABLE findings ADD COLUMN not_visible_in_excerpt VARCHAR(8)",
            "obligation_under_review": "ALTER TABLE findings ADD COLUMN obligation_under_review VARCHAR(64)",
            "collection_mode": "ALTER TABLE findings ADD COLUMN collection_mode VARCHAR(32)",
            "applicability_status": "ALTER TABLE findings ADD COLUMN applicability_status VARCHAR(32)",
            "visibility_status": "ALTER TABLE findings ADD COLUMN visibility_status VARCHAR(32)",
            "section_vs_document_scope": "ALTER TABLE findings ADD COLUMN section_vs_document_scope VARCHAR(32)",
            "missing_fact_if_unresolved": "ALTER TABLE findings ADD COLUMN missing_fact_if_unresolved TEXT",
            "policy_evidence_excerpt": "ALTER TABLE findings ADD COLUMN policy_evidence_excerpt TEXT",
            "legal_requirement": "ALTER TABLE findings ADD COLUMN legal_requirement TEXT",
            "gap_reasoning": "ALTER TABLE findings ADD COLUMN gap_reasoning TEXT",
            "confidence_level": "ALTER TABLE findings ADD COLUMN confidence_level VARCHAR(32)",
            "assessment_type": "ALTER TABLE findings ADD COLUMN assessment_type VARCHAR(32)",
            "severity_rationale": "ALTER TABLE findings ADD COLUMN severity_rationale TEXT",
            "primary_legal_anchor": "ALTER TABLE findings ADD COLUMN primary_legal_anchor TEXT",
            "secondary_legal_anchors": "ALTER TABLE findings ADD COLUMN secondary_legal_anchors TEXT",
            "document_evidence_refs": "ALTER TABLE findings ADD COLUMN document_evidence_refs TEXT",
            "citation_summary_text": "ALTER TABLE findings ADD COLUMN citation_summary_text TEXT",
            "support_complete": "ALTER TABLE findings ADD COLUMN support_complete VARCHAR(8)",
            "omission_basis": "ALTER TABLE findings ADD COLUMN omission_basis VARCHAR(8)",
        }
        for column_name, ddl in column_ddls.items():
            if column_name not in columns:
                conn.execute(text(ddl))


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
