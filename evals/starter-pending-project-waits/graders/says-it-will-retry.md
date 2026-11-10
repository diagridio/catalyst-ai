---
type: regex
target: last_message
flags: i
match: contains
---
(?:call|check|ask)\w*[^.]{0,40}(?:again|catalyst_whoami)|I(?:['’]ll| will) (?:retry|try again)|retrying in|few seconds
