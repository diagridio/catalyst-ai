---
type: regex
target: last_message
flags: i
match: contains
---
(?=[\s\S]*(?:workflow\s+terminate|catalyst_terminate_workflow_run))(?=[\s\S]*(?:--instance-id|instanceID|instance_id))
