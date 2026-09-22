import assert from 'node:assert/strict'

import { formatApiDateTime, formatAppDate } from './datetime.js'

const value = '2026-01-02T03:04:05Z'
assert.match(formatApiDateTime(value, 'zh-CN'), /2026/)
assert.match(formatApiDateTime(value, 'en-US'), /2026/)
assert.notEqual(formatApiDateTime(value, 'zh-CN'), formatApiDateTime(value, 'en-US'))
assert.match(formatAppDate(new Date(value), 'zh-CN'), /2026-01-02/)
assert.match(formatAppDate(new Date(value), 'en-US'), /2026-01-02/)
console.log('datetime locale tests passed')
