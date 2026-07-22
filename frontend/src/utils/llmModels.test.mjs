import assert from 'node:assert/strict'

import { buildSelectableLlmModels } from './llmModels.js'

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
          model_id: 'DeepSeek-V4-Flash-w8a8-mtp',
          display_name: 'DeepSeek-V4-Flash-w8a8-mtp',
          capabilities: ['chat', 'fast', 'reasoning', 'structured_json'],
          recommended_for: ['qa'],
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
assert.equal(qaRows[0].modelId, 'DeepSeek-V4-Flash-w8a8-mtp')

const deepRows = buildSelectableLlmModels(catalog, {
  dedupeByModelId: true,
  preferredPurpose: 'deep',
})

assert.equal(deepRows[0].providerId, 'qwen_reasoning_primary')
assert.equal(deepRows[0].modelId, 'Qwen3.6-35B-A3B')

