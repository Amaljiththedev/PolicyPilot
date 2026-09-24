from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, auth
from app.api.services.embeddings import warm_up
from app.api.routes import document_upload
from app.api.routes import search
@asynccontextmanager
async def lifespan(app: FastAPI):
    warm_up()
    yield


app = FastAPI(
    title="PolicyPilot API",
    description="RAG-powered Policy Assistant backend with Claude agent orchestration",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire in API routers under /api/v1
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(document_upload.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")

@app.get("/")
def root():
    """Root endpoint."""
    return {"message": "Welcome to PolicyPilot API. Visit /docs for documentation."}
