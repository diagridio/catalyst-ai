---
type: regex
target: last_message
flags: i
match: contains
---
data[- ]sharing|withheld|withhold|not shared|elid|redact|metadata\W{0,3}(?:level|shape|posture|view)|absent[\s\S]{0,80}(?:not|rather than|different)|(?:not|rather than)[\s\S]{0,40}(?:empty|null)|can(?:'|no)t (?:see|read)\b[^.]{0,60}(?:output|input|status|payload|data|field)|unable to see|don'?t have access|(?:is|are|was|were|stays?|kept) hidden|hidden from|not (?:visible|available) to|not allowed to (?:read|see)|(?:doesn'?t|does not|won'?t) (?:let|allow) AI|(?:doesn'?t|does not|won'?t) share|lets AI tools|never reached
