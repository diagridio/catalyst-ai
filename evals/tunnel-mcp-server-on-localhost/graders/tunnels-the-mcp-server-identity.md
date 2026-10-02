---
type: regex
target: last_message
flags: i
match: contains
---
diagrid dev run(?:[^\n`]|\\\n)*(?:--id|-a)[ =]travel
