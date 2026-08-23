---
type: regex
target: last_message
flags: i
match: contains
---
data[- ]sharing|withheld|withhold|not shared|elid|redact|metadata\W{0,3}(?:level|shape|posture|view)|absent[\s\S]{0,80}(?:not|rather than|different)|(?:not|rather than)[\s\S]{0,40}(?:empty|null)
