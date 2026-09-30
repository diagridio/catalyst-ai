---
type: llm
focus: last_message
---
The user wants a second managed pub/sub broker inside one Catalyst project and has
offered to upgrade their plan to get it. The real limit is one managed pub/sub per
project on every plan, and no plan change
raises it. A per-organization override exists, so the live quota is the authority
over the remembered 1.

PASS if the response tells the user an upgrade will not get them a second broker,
and describes the shape that does work — one broker with the analytics traffic
separated by topic.

FAIL if the response does any of these:
- says or implies that upgrading, changing plan, or moving off the free tier is
  how to get a second pub/sub in the project;
- presents the single pub/sub as a free-tier restriction;
- proposes a second Catalyst project as the way to get a second managed broker
  without saying that this spends a project slot and is not the intended shape;
- claims to have created a pub/sub.

Saying that the live quota should be read (for example with `diagrid org usage`)
because an organization may hold a negotiated override is a PASS, not a hedge.
Telling the user that a genuinely exhausted cap is a support conversation rather
than a plan change is also a PASS.
