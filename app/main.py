from fastapi import FastAPI, HTTPException

from app.agent import DeepResearchAgent
from app.logging_utils import configure_logging
from app.schemas import DeepResearchRequest, DeepResearchResponse, ToolExecutionRequest, ToolExecutionResponse

configure_logging()

app = FastAPI(title="Minimal SearXNG Research Agent", version="0.2.0")
deep_agent = DeepResearchAgent()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tools")
def list_tools() -> list[dict]:
    return deep_agent.tools.list_descriptions()


@app.post("/tool-call", response_model=ToolExecutionResponse)
def execute_tool(request: ToolExecutionRequest) -> ToolExecutionResponse:
    try:
        result = deep_agent.tools.execute(request.name, request.arguments)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ToolExecutionResponse(name=request.name, result=result)


@app.post("/deep-research", response_model=DeepResearchResponse)
def deep_research(request: DeepResearchRequest) -> DeepResearchResponse:
    try:
        return deep_agent.run(
            question=request.question,
            save_markdown=request.save_markdown,
            output_dir=request.output_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}") from exc
