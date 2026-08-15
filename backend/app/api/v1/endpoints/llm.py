"""LLM 接口 — 问答对话与实验建议。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.core.auth import require_admin
from app.core.llm_client import chat
from app.core.logging import get_logger
from app.schemas.common import ApiResponse
from app.schemas.llm_models import LLMModelCatalogData
from app.schemas.llm_models import LLMConfigSchemaData
from app.schemas.llm_models import LLMRoutingData
from app.schemas.llm_models import LLMRoutingUpdateRequest
from app.services.llm_config_schema_service import build_config_schema_data
from app.services.llm_model_service import LLMModelService

logger = get_logger("poly_agent.llm")

router = APIRouter(tags=["LLM 问答与建议"])
model_service = LLMModelService()


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    return current_user["user_id"] if current_user else "demo_user"


class ChatRequest(BaseModel):
    """对话请求。"""
    messages: list[dict] = Field(..., description="消息列表 [{role, content}, ...]")
    provider_id: str | None = Field(default=None, description="可选 provider id")
    model: str | None = Field(default=None, description="可选模型 id")
    purpose: str = Field(default="qa", description="用途路由 qa/deep/report")


class ChatResponse(BaseModel):
    """对话响应。"""
    content: str = Field(..., description="模型回复内容")


class ExperimentSuggestRequest(BaseModel):
    """实验建议请求。"""
    variables: list[dict] = Field(..., description="搜索空间变量列表")
    experiments: list[dict] = Field(default_factory=list, description="已有实验数据（完整记录）")
    n_suggestions: int = Field(default=3, description="建议数量")


class ExperimentSuggestResponse(BaseModel):
    """实验建议响应。"""
    suggestions: list[dict] = Field(..., description="建议的实验条件列表")
    reasoning: str = Field(default="", description="建议理由")


SYSTEM_PROMPT_EXPERIMENT = (
    "你是一位高分子材料实验设计专家。"
    "根据提供的变量搜索空间和已有实验数据，推荐下一组最有价值的实验条件。"
    "请以 JSON 格式返回，格式为："
    '{"suggestions": [{"变量1": 值1, "变量2": 值2}, ...], "reasoning": "建议理由"}'
    "只返回 JSON，不要包含其他文字。"
)


@router.post("/chat", response_model=ChatResponse)
async def chat_completion(request: ChatRequest):
    """通用对话接口 — 发送消息列表并返回模型回复。

    可用于问答对话页面的 LLM 交互。
    """
    try:
        content = chat(
            request.messages,
            provider_id=request.provider_id,
            model=request.model,
            purpose=request.purpose,
        )
        return ChatResponse(content=content)
    except Exception as e:
        logger.error(f"LLM 对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {str(e)}")


@router.get("/models", response_model=ApiResponse[LLMModelCatalogData])
def list_llm_models() -> ApiResponse[LLMModelCatalogData]:
    """List sanitized selectable LLM models and routing defaults."""
    return ApiResponse(data=model_service.get_catalog(probe=False))


@router.post(
    "/models/check",
    response_model=ApiResponse[LLMModelCatalogData],
    dependencies=[Depends(require_admin)],
)
def check_llm_models() -> ApiResponse[LLMModelCatalogData]:
    """Refresh LLM provider readiness and discovered models."""
    return ApiResponse(data=model_service.get_catalog(probe=True))


@router.get("/routing", response_model=ApiResponse[LLMRoutingData])
def get_llm_routing() -> ApiResponse[LLMRoutingData]:
    """Return global default LLM routes."""
    return ApiResponse(data=model_service.get_routing())


@router.get("/config-schema", response_model=ApiResponse[LLMConfigSchemaData])
def get_llm_config_schema() -> ApiResponse[LLMConfigSchemaData]:
    """Return the LLM provider configuration schema catalog for the Admin page."""
    return ApiResponse(data=build_config_schema_data())


@router.put(
    "/routing",
    response_model=ApiResponse[LLMRoutingData],
    dependencies=[Depends(require_admin)],
)
def update_llm_routing(
    payload: LLMRoutingUpdateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[LLMRoutingData]:
    """Update global default LLM routes."""
    return ApiResponse(data=model_service.update_routing(payload, actor_user_id=_actor_user_id(current_user)))


@router.post("/suggest-experiments", response_model=ExperimentSuggestResponse)
async def suggest_experiments(request: ExperimentSuggestRequest):
    """LLM 辅助实验建议 — 根据搜索空间和已有数据推荐下一步实验条件。

    返回建议的实验点列表及推理说明。
    """
    def _format_var(v: dict) -> str:
        name = v.get('name', '?')
        vtype = v.get('type', '?')
        if vtype in ('real', 'integer'):
            bounds = v.get('bounds') or [v.get('low', '?'), v.get('high', '?')]
            return f"- {name}（类型: {vtype}, 范围: {bounds[0]}~{bounds[1]}）"
        return f"- {name}（类型: {vtype}, 可选值: {v.get('values') or v.get('categories', '?')}）"

    variable_desc = "\n".join(_format_var(v) for v in request.variables)

    if request.experiments:
        exp_lines = []
        for i, exp in enumerate(request.experiments):
            inputs = exp.get("inputs", exp)
            output = exp.get("output", "?")
            parts = ", ".join(f"{k}={v}" for k, v in inputs.items() if k not in ("output", "Output", "noise", "Noise", "iteration", "Iteration", "reason", "Reason"))
            exp_lines.append(f"  {i+1}. {parts} → Output={output}")
        exp_text = f"已完成 {len(request.experiments)} 组实验：\n" + "\n".join(exp_lines)
    else:
        exp_text = "暂无实验数据"

    user_message = (
        f"## 搜索空间\n{variable_desc}\n\n"
        f"## 已有实验数据\n{exp_text}\n\n"
        f"请根据以上实验数据，推荐 {request.n_suggestions} 组下一步最有价值的实验条件。"
        f"优先在现有数据的空白区域或极值方向探索，给出具体数值。"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_EXPERIMENT},
        {"role": "user", "content": user_message},
    ]

    try:
        content = chat(messages, temperature=0.7)
        import json
        result = json.loads(content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        return ExperimentSuggestResponse(
            suggestions=result.get("suggestions", []),
            reasoning=result.get("reasoning", ""),
        )
    except json.JSONDecodeError:
        return ExperimentSuggestResponse(
            suggestions=[],
            reasoning=content,
        )
    except Exception as e:
        logger.error(f"LLM 实验建议失败: {e}")
        raise HTTPException(status_code=500, detail=f"LLM 实验建议失败: {str(e)}")
