from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class ChatResponse(BaseModel):
    response: str


class ServerStatus(BaseModel):
    connected: bool
    tools: list[str] = Field(default_factory=list)
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    model: str
    servers: dict[str, ServerStatus]
