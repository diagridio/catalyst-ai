---
type: regex
target: last_message
flags: i
match: contains
---
(?=[\s\S]*(?:defaultWorkflowStoreEnabled|workflow store))(?=[\s\S]*(?:defaultPubsubEnabled|pub/?sub))(?=[\s\S]*(?:defaultKVStoreEnabled|KV store|key[- ]value store))
