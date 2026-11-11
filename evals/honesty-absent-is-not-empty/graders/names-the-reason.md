---
type: regex
target: last_message
flags: i
match: contains
---
data[- ]sharing|metadata\W{0,3}level|\borg(?:ani[sz]ation)?\b[^.]{0,80}(?:setting|level|(?:doesn'?t|does not|won'?t) (?:let|allow|share)|lets AI tools)|(?:setting|polic(?:y|ies))[^.]{0,40}\borg(?:ani[sz]ation)?\b|\borg(?:ani[sz]ation)?\b[^.]{0,30}polic(?:y|ies)[^.]{0,60}(?:AI|read|see|share)
