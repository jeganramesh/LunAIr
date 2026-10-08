from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from lunair.api.routes.chat import router_api as chat_router
from lunair.api.routes.models import models_api as models_router
from lunair.config import settings
from lunair.schemas.chat import ChatCompletionRequest
from lunair.schemas.common import HealthResponse

app = FastAPI(
    title="LunAIR",
    version=settings.version,
    description="LLM Unified Native AI Inference Router",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(models_router)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        version=settings.version,
        gateway_mode=settings.gateway_mode,
        details={"fastapi_url": settings.fastapi_url},
    )


@app.post("/v1/echo")
async def echo_request(req: ChatCompletionRequest):
    return req.model_dump()
