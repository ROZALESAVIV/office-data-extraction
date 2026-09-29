import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import auth, cases, documents, review, senders

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Re-queue documents whose extraction job died with the process.

    Without this a crash leaves them in 'extracting' for ever, because the
    lease that says a worker owns them is never released.
    """
    try:
        from app.services import extraction

        stalled = extraction.recover_stalled()
        for document_id, tenant_id in stalled:
            extraction.run(document_id, tenant_id)
        if stalled:
            log.info("re-queued %d stalled documents", len(stalled))
    except Exception:
        log.exception("startup recovery failed; continuing")
    yield


app = FastAPI(title="Office Data Extraction", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(senders.router)
app.include_router(documents.router)
app.include_router(review.router)


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}
