"""FastAPI example: wrap an existing LLM call with Onion governance.

Install optional dependencies:

    pip install fastapi uvicorn

Run:

    uvicorn examples.fastapi_governance:app --reload
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Header
from pydantic import BaseModel

from onion_core import AgentContext, CallableProvider, Pipeline


async def existing_llm_call(context: AgentContext) -> str:
    """Replace this with your real SDK/client call."""
    user_text = context.messages[-1].text_content
    tenant_id = context.metadata.get("tenant_id", "anonymous")
    return f"[tenant={tenant_id}] {user_text}"


pipeline = Pipeline.governed(
    provider=CallableProvider(existing_llm_call, model="internal-chat"),
    preset="balanced",
    name="fastapi-governed-chat",
)

app = FastAPI()


class ChatRequest(BaseModel):
    message: str
    metadata: dict[str, Any] = {}


class ChatResponse(BaseModel):
    content: str | None


@app.on_event("startup")
async def startup() -> None:
    await pipeline.startup()


@app.on_event("shutdown")
async def shutdown() -> None:
    await pipeline.shutdown()


@app.post("/chat")
async def chat(
    body: ChatRequest,
    x_tenant_id: Annotated[str, Header()] = "anonymous",
) -> ChatResponse:
    metadata = {"tenant_id": x_tenant_id, **body.metadata}
    response = await pipeline.complete(
        body.message,
        metadata=metadata,
        config={"tenant_id": x_tenant_id},
    )
    return ChatResponse(content=response.content)
