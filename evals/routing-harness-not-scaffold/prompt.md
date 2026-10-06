---
name: routing-harness-not-scaffold
description: A hand-written model loop that must survive restarts fires catalyst-agent-harness and must not fire catalyst-agent-scaffold, whose route is a framework adapter. The pair that decides whether a custom loop gets taken over or replaced.
tags: [routing]
plugins: ["../.."]
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: >
  catalyst-agent-harness fires and catalyst-agent-scaffold does not. The answer keeps the
  user's own loop and gives every model call and every function call its own durable
  step. The prompt avoids "agent", "workflow", "activity", "tool", "harness" and
  "durable" so neither skill can win on a keyword echo.
---

Our support bot is about eighty lines of Python: a while loop that sends the conversation
to the model API, runs whichever of our functions the reply asks for, appends what they
return, and goes round again until the model stops asking. When the process dies half way
through, the conversation is gone and we pay for every model call again from the start.
Make that loop pick up where it stopped using Dapr, without moving us onto a framework.
