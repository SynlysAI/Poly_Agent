import assert from 'node:assert/strict'

import {
  buildSelectableLlmModels,
  modelLacksToolCalling,
  resolveDefaultModelSelection,
  shouldKeepManualModelSelection,
} from './llmModels.js'

const catalog = {
  routing: {},
  providers: [
    {
      provider_id: 'qwen_reasoning_primary',
      display_name: 'Qwen Reasoning Primary',
      status: 'unknown',
      models: [
        {
          model_id: 'Qwen3.6-35B-A3B',
          display_name: 'Qwen3.6-35B-A3B',
          capabilities: ['chat', 'reasoning', 'long_context', 'structured_json'],
          recommended_for: ['deep'],
        },
      ],
    },
    {
      provider_id: 'default_openai',
      display_name: 'Default chat model',
      status: 'unknown',
      models: [
        {
          model_id: 'legacy-fast-model',
          display_name: 'legacy-fast-model',
          capabilities: ['chat', 'fast', 'reasoning', 'structured_json', 'tool_calling'],
          recommended_for: ['qa'],
          tool_protocol: 'openai_chat_tools',
          supports_parallel_tool_calls: true,
          context_window: 131072,
          capability_source: 'configured',
        },
      ],
    },
  ],
}

const qaRows = buildSelectableLlmModels(catalog, {
  dedupeByModelId: true,
  preferredPurpose: 'qa',
})

assert.equal(qaRows[0].providerId, 'default_openai')
assert.equal(qaRows[0].modelId, 'legacy-fast-model')

const deepRows = buildSelectableLlmModels(catalog, {
  dedupeByModelId: true,
  preferredPurpose: 'deep',
})

assert.equal(deepRows[0].providerId, 'qwen_reasoning_primary')
assert.equal(deepRows[0].modelId, 'Qwen3.6-35B-A3B')

const toolRow = qaRows.find((row) => row.modelId === 'legacy-fast-model')
assert.equal(toolRow.toolProtocol, 'openai_chat_tools')
assert.equal(toolRow.supportsParallelToolCalls, true)
assert.equal(toolRow.contextWindow, 131072)
assert.equal(toolRow.capabilitySource, 'configured')
assert.ok(toolRow.capabilities.includes('tool_calling'))

const routing = {
  qa: { provider_id: 'default_openai', model_id: 'legacy-fast-model' },
  deep: { provider_id: 'qwen_reasoning_primary', model_id: 'Qwen3.6-35B-A3B' },
}

assert.deepEqual(
  resolveDefaultModelSelection(qaRows, {
    urlModel: { providerId: 'qwen_reasoning_primary', modelId: 'Qwen3.6-35B-A3B' },
    chatModel: { providerId: 'default_openai', modelId: 'legacy-fast-model' },
    routing,
    purpose: 'qa',
  }),
  { key: 'qwen_reasoning_primary::Qwen3.6-35B-A3B', origin: 'url' },
)

assert.deepEqual(
  resolveDefaultModelSelection(qaRows, {
    chatModel: { providerId: 'qwen_reasoning_primary', modelId: 'Qwen3.6-35B-A3B' },
    routing,
    purpose: 'qa',
  }),
  { key: 'qwen_reasoning_primary::Qwen3.6-35B-A3B', origin: 'chat' },
)

assert.deepEqual(
  resolveDefaultModelSelection(deepRows, { routing, purpose: 'deep' }),
  { key: 'qwen_reasoning_primary::Qwen3.6-35B-A3B', origin: 'route' },
)

assert.deepEqual(
  resolveDefaultModelSelection(qaRows, { routing: {}, purpose: 'qa' }),
  { key: 'default_openai::legacy-fast-model', origin: 'route' },
)

assert.deepEqual(
  resolveDefaultModelSelection([toolRow], { routing: {}, purpose: 'deep' }),
  { key: 'default_openai::legacy-fast-model', origin: 'fallback' },
)

assert.equal(
  shouldKeepManualModelSelection('user', 'default_openai::legacy-fast-model', qaRows),
  true,
)
assert.equal(
  shouldKeepManualModelSelection('url', 'qwen_reasoning_primary::Qwen3.6-35B-A3B', qaRows),
  true,
)
assert.equal(
  shouldKeepManualModelSelection('chat', 'default_openai::legacy-fast-model', qaRows),
  false,
)
assert.equal(
  shouldKeepManualModelSelection('user', 'missing::model', qaRows),
  false,
)

assert.equal(modelLacksToolCalling(toolRow, ['algorithm:demo']), false)
assert.equal(modelLacksToolCalling(qaRows[1], ['algorithm:demo']), true)
assert.equal(modelLacksToolCalling(toolRow, []), false)
assert.equal(modelLacksToolCalling(null, ['algorithm:demo']), false)

console.log('llm model helpers tests passed')
