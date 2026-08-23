---
type: regex
target: last_message
flags: i
match: contains
---
(?=[\s\S]*acme-staging)(?=[\s\S]*acme-prod)
