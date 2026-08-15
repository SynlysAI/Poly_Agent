# LLM Provider 配置 Schema

> 生成自 `backend.app.schemas.llm_models.LLMProviderConfigInput`，schema version：1。

本页与 `docs/llm-provider-config-schema.json` 同源。配置错误路径用于定位环境变量 JSON 或 `backend/config/llm.providers.json` 中的具体字段。

## Provider 字段

| 字段 | 说明 | 类型 | 默认值 | 约束 | 错误路径 |
|---|---|---|---|---|---|
| `provider_id` | 唯一 provider ID | string | null | minLength=1；maxLength=120 | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.provider_id` |
| `display_name` | 前端展示名称 | string | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.display_name` |
| `provider_type` | provider 协议类型：openai_compatible / ollama / custom_http | string | openai_compatible | enum=["openai_compatible", "ollama", "custom_http"] | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.provider_type` |
| `base_url` | OpenAI 兼容 API Base URL | string | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.base_url` |
| `api_key_env` | API Key 环境变量名，必须为大写标识 | string | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.api_key_env` |
| `model` | 兼容旧配置的单一模型 ID | string | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.model` |
| `models` | 模型 ID 字符串或 per-model 对象配置 | array<string | LLMModelConfigInput> | [] | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models` |
| `capabilities` | provider 级能力集合；未单独配置的模型继承该集合 | array<string> | ["chat"] | items_enum=["chat", "fast", "reasoning", "structured_json", "tool_calling", "long_context", "local"] | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.capabilities` |
| `recommended_for` | provider 级推荐用途路由 | array<string> | [] | items_enum=["qa", "deep", "report"] | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.recommended_for` |

## Per-model 字段

| 字段 | 说明 | 类型 | 默认值 | 约束 | 错误路径 |
|---|---|---|---|---|---|
| `model_id` | 模型 ID，用于请求 provider 时的 model 参数 | string | null | minLength=1；maxLength=200 | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].model_id` |
| `display_name` | 前端展示名称 | string | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].display_name` |
| `capabilities` | 模型能力集合 | array<string> | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].capabilities` |
| `recommended_for` | 推荐用途路由 | array<string> | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].recommended_for` |
| `context_window` | 上下文窗口 token 上限 | integer | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].context_window` |
| `max_output_tokens` | 单次输出 token 上限 | integer | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].max_output_tokens` |
| `tool_protocol` | 工具调用协议标识 | string | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].tool_protocol` |
| `supports_parallel_tool_calls` | 是否支持并行工具调用 | boolean | null | - | `LLM_PROVIDER_CONFIGS_FILE[].<provider>.models[].supports_parallel_tool_calls` |
