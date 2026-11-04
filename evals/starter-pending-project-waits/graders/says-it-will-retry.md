---
type: regex
target: last_message
flags: i
match: contains
---
(?:call|check|ask)\w*[^.]{0,40}(?:again|catalyst_whoami)|retry|few seconds
