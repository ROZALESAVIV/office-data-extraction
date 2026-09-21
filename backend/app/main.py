from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import auth, cases, documents, senders

app = FastAPI(title="Office Data Extraction")

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


@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok"}
