# Google Cloud Gen AI Academy APAC Edition on Hack2Skill — Demo Video Script

Target length: 1 minute 45 seconds to 2 minutes (aim: 1:55)

## Narration and Demo Prompts

### 0:00–0:12 — Introduction

"Hello! For the **Google Cloud Gen AI Academy APAC Edition on Hack2Skill**, I
built one secure assistant for tasks, notes, schedules, and insights—putting the
Academy's Learn, Challenge, Build journey into practice."

Show the live application and the single `productivity_assistant` entry.

### 0:12–0:23 — Multi-agent assistant

"Gemini 2.5 Flash on Vertex AI and Google Agent Development Kit route each
request to the right specialist, while MCP exposes only approved tools."

Prompt:

> What can you do? Give me one short example for each capability.

### 0:23–0:38 — Task assistant

Prompt:

> Create a high-priority task titled "Submit weekly status report" with the
> description "Summarize completed work and next steps" and due date
> 2026-07-24.

Then show structured results with:

> List all pending tasks.

"The task specialist converts natural language into structured work stored in
AlloyDB."

### 0:38–0:56 — Notes assistant and semantic search

Prompt:

> Create a note titled "Focus routine" with content "Silence notifications,
> choose one important task, and work without interruptions for 45 minutes."
> Add the tags "productivity,focus".

Then demonstrate meaning-based retrieval:

> Search my notes for ideas about reducing distractions and doing focused work.

"AlloyDB AI uses Vertex AI embeddings to find notes by meaning, not just
matching keywords."

### 0:56–1:09 — Calendar assistant

Prompt:

> Schedule an event titled "Weekly planning session" on 2026-07-23 at 16:00
> for 30 minutes with the description "Review priorities for the coming week".

Then show:

> List all events on 2026-07-23.

"The calendar specialist creates the event and retrieves the day's schedule."

### 1:09–1:20 — Live analytics assistant

Use the ID returned by the task assistant:

> Mark task ID <TASK_ID> as completed.

Then ask:

> Show my task completion rate by priority and summarize today's activity.

"BigQuery reads AlloyDB through a read-only federated connection, making the
completed task immediately visible without copying data."

### 1:20–1:50 — Google Cloud architecture

"Cloud Run hosts the public assistant, IAM-protected MCP Toolbox, and migration
Job. AlloyDB and AlloyDB AI provide storage and vector search, while BigQuery
and the BigQuery Connection API enable live analytics. Secret Manager protects
credentials; Cloud Build and Artifact Registry deliver containers; and Cloud
IAM enforces least privilege."

"A custom VPC, subnet, Private Services Access, Service Networking, and Direct
VPC egress keep traffic private. Cloud Logging, Cloud Monitoring, and Cloud
Billing Budgets provide operational and cost visibility."

### 1:50–1:57 — Closing

"The result is a practical, secure assistant built with Google Cloud for the
Gen AI Academy APAC Edition on Hack2Skill. Thank you."

## GCP Services and Networking Checklist

- **Vertex AI:** Gemini 2.5 Flash inference and text embedding model access.
- **Cloud Run:** public assistant, IAM-protected MCP Toolbox, and migration Job.
- **AlloyDB and AlloyDB AI:** typed application data, vector embeddings, and semantic search.
- **BigQuery and BigQuery Connection API:** live read-only AlloyDB federation and analytics views.
- **Secret Manager:** numeric database credential versions.
- **Cloud Build and Artifact Registry:** immutable container builds and image storage.
- **Cloud IAM:** dedicated least-privilege service accounts and private service invocation.
- **VPC networking:** custom VPC, regional subnet, Private Services Access,
  **Service Networking**, private IP, and Cloud Run **Direct VPC egress**.
- **Cloud Logging and Cloud Monitoring:** logs, uptime checks, latency, 5xx, and connection alerts.
- **Cloud Billing Budgets:** project-scoped cost thresholds and guardrails.

## Complete Screen Flow

1. **0:00–0:12:** Show the title card, live application, and the single
   `productivity_assistant` selector entry.
2. **0:12–0:23:** Ask the capability prompt and flash the four-agent graph.
3. **0:23–0:38:** Create the task, cut directly to its result, and list pending tasks.
4. **0:38–0:56:** Create the note, then cut to the semantic-search result.
5. **0:56–1:09:** Create the calendar event and briefly show the event list.
6. **1:09–1:20:** Complete the created task, then show the refreshed live analytics.
7. **1:20–1:28:** Show Cloud Run services and the migration Job.
8. **1:28–1:35:** Show AlloyDB private connectivity, tables, and BigQuery views.
9. **1:35–1:42:** Montage Secret Manager names, Cloud Build, Artifact Registry,
   and IAM service accounts. Never open secret values.
10. **1:42–1:50:** Montage the VPC, subnet, private-services peering, Direct VPC
    egress, Cloud Logging, Cloud Monitoring, and Cloud Billing Budget.
11. **1:50–1:57:** Return to the assistant and close on the **Google Cloud Gen AI
    Academy APAC Edition on Hack2Skill** title.

## Demo Safety and Delivery Tips

- Use only the synthetic prompts above; do not enter personal or sensitive data.
- Replace `<TASK_ID>` with the ID returned during the recording.
- Start a new chat session before recording so debug event history is short.
- The `#` labels in ADK Dev UI are event sequence numbers, not part of the answer.
- Keep tool-call details collapsed unless explaining the MCP workflow.
- Pause briefly after each final formatted answer so viewers can read it.
- Never display database passwords, access tokens, secret payloads, or raw request headers.
