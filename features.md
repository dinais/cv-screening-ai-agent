# Incremental Features Map: Candidate Screening System

This document breaks down the system development into distinct, incrementally deliverable features based on the system architecture and requirements.

## Feature 1: Project Setup and Basic UI
* **Goal:** Initialize the Flask application, GitHub repository, and serve the basic frontend[cite: 1].
* **Tasks:**
  * Setup Flask environment and project structure.
  * Create basic HTML/CSS templates for the UI (following UI/UX principles)[cite: 1].
  * Implement user authentication (Login/Logout for HR and Candidates)[cite: 1].

## Feature 2: Core Data Infrastructure (Event Sourcing)
* **Goal:** Implement the database connection and the Event Sourcing pattern[cite: 1].
* **Tasks:**
  * Connect to the cloud database (e.g., Somee.com)[cite: 1].
  * Create the `EventStore` table.
  * Implement the base Command and Query handlers (CQRS structure)[cite: 1].

## Feature 3: Core Entities and Query Model
* **Goal:** Record jobs and applications as events, and rebuild the current state for the UI by replaying those events. No ORM. Commands only append. Queries only read.
* **Entities:**
  * **Job:** An open role created by an HR user.
  * **Application:** One candidate's submission for one job. The candidate is the logged-in account, identified by email. Login accounts stay the mock users from Feature 1: the HR account, `CANDIDATE_EMAIL`, and any extra candidate pairs in `EXTRA_CANDIDATES`.
* **Events:**
  * `JobCreated` — aggregate type `Job`. Payload: `job_id`, `title`, `requirements`, `created_by`. Appended by `CreateJobCommand` when HR submits the new-job form. A missing title or missing requirements is rejected before any database write.
  * `JobClosed` — aggregate type `Job`, same aggregate id as `JobCreated`. Payload: `job_id`, `closed_by` (the logged-in HR email). Appended by `CloseJobCommand`. The `JobCreated` row is not updated or deleted. A missing `job_id` or `closed_by`, an unknown job, or a stream that already contains `JobClosed` is rejected before any database write. HR cannot reopen a job.
  * `ApplicationSubmitted` — aggregate type `Application`. Payload: `application_id`, `job_id`, `full_name`, `email`, `cv_text`. Appended by `SubmitApplicationCommand` when a candidate submits the form for one job. `cv_text` is plain text. A missing name, a missing job, or an unknown job is rejected before any database write. Before appending, the command reads existing `ApplicationSubmitted` events and rejects the command when this email has already applied to this `job_id`. That rejection also happens before any database write. Embeddings are Feature 4.
* **Query Model:**
  * The read side loads `JobCreated` and `ApplicationSubmitted` from the Event Store in order and replays them. It does not update or delete rows.
  * Each `JobCreated` becomes an open job with status Open. A later `JobClosed` for that `job_id` changes the replayed status to Closed.
  * Each `ApplicationSubmitted` is attached to that job, increases its applicant count, and records that applicant's `full_name`, `email`, and `cv_text`.
  * The HR dashboard shows the open-job count, the applicant count for open jobs only, and a table of open jobs. A closed job is left out of that table, the counts, and HR search. `GET /hr/jobs/<job_id>` still shows a closed job, with status Closed, so its applicants and assessments remain reachable by id.
  * The HR job drill-down shows the requirements, the applicant count, and the list of applicants (`full_name`, `email`, and `cv_text`).
  * The candidate dashboard lists open jobs only. A closed job is not listed and its apply URL returns 404. `SubmitApplicationCommand` also rejects a closed job before any write. The query takes the logged-in candidate's email. A job with no `ApplicationSubmitted` for that email is marked not applied. A job that already has one is marked applied.
* **Search (HR):**
  * The HR dashboard has a search box. It submits `GET /hr/?q=<text>`. Nothing is written.
  * Matching is a case-insensitive substring match on the replayed state. A job matches when `q` is in its `title` or `requirements`. An applicant matches when `q` is in `full_name`, `email`, or `cv_text`.
  * With a non-empty `q`, the jobs table shows only matching jobs, and a "Matching applicants" table lists each matching applicant with name, email, job title, and assessment status. The stat cards still show the totals.
  * An empty or blank `q` shows the normal dashboard with no applicants table.
* **Candidate drill-down (HR):**
  * `GET /hr/applications/<application_id>` shows one application: the job title (linked to the job drill-down), the job requirements, the applicant's `full_name`, `email`, and `cv_text`, and the Feature 5 assessment when there is one.
  * Every applicant row on the job drill-down and in the search results opens this page when clicked.
  * An unknown `application_id` returns 404. A candidate account gets 403.
* **Tasks:**
  * HR form to create a job, the jobs table, and the drill-down fed by the projection.
  * Candidate dashboard: each open job shows an Apply action, or an Applied indicator when this candidate has already applied. There is no generic job dropdown.
  * Apply action opens a form for that job only. The form collects the candidate's name and `cv_text`. After a successful submit, the candidate returns to the dashboard and that job shows Applied.
  * Command: `CreateJobCommand` -> append `JobCreated`.
  * Command: `CloseJobCommand` -> append `JobClosed`. The HR dashboard and the job page post this when the job is Open. A candidate account gets 403. The evaluation agent does not issue this command.
  * Command: `SubmitApplicationCommand` -> append `ApplicationSubmitted`, or reject a duplicate application for the same email and `job_id`.
  * Query: replay the events into the HR dashboard, the HR applicant list, and the candidate dashboard.
  * Query: HR search over jobs and applicants, and the single-application drill-down.

## Feature 4: Vector Database Integration
* **Goal:** Turn each submitted CV into an embedding and store that vector for later semantic search. The Event Store stays the source of truth.
* **Vector store:** ChromaDB, persisted at `VECTOR_DB_PATH`. One collection, `cv_embeddings`.
* **Embedding:** A local Ollama server, as required by the course architecture (`ollama + Docker`). Base URL `http://localhost:11434`. Model `nomic-embed-text`. The input is the plain `cv_text` on `ApplicationSubmitted`. No file parsing and no OpenAI call.
* **Write boundary:** `SubmitApplicationCommand` only appends `ApplicationSubmitted`. It does not call Ollama and it does not write to Chroma. After that append succeeds, the controller runs a projector. The projector reads that event, requests the embedding from local Ollama, and upserts one vector. The event row is not updated or deleted.
* **Identity:** The vector id is `application_id`. Metadata stores `job_id`, `email`, and `full_name`. The text stored with the vector is `cv_text`.
* **Replay:** A missing vector can be rebuilt by reading `ApplicationSubmitted` again and embedding any application id that is not already in Chroma. That rebuild does not append a new event. A failed embedding does not remove the application event.
* **Tasks:**
  * Keep the Feature 3 application form and `ApplicationSubmitted` event.
  * Add the Chroma collection and the local Ollama embedding call (`ollama + Docker`).
  * Project `cv_text` into Chroma after a successful application.
  * Searching those vectors against a job's requirements is Feature 5.

## Feature 5: Candidate Evaluation Agent
* **Purpose:** Decide whether a submitted candidate fits one job. The agent runs outside Flask, compares the CV with the job requirements, checks public industry context, and records an assessment the HR user can read.
* **Runtime:** The Deep Agent framework, as required by the course architecture. It is a separate process (`python -m src.agents`). It does not run inside a Flask request and does not block the web server. Model calls go through the `LLMProvider` interface below. No OpenAI call.
* **Model provider abstraction (`LLMProvider`):**
  * One interface with two operations:
    * `embed(text) -> list[float]` — turns text into a vector.
    * `evaluate(evidence) -> dict` — returns one evaluation report in the JSON shape described under Expected output.
  * The Feature 4 projector and the RAG query call `embed`. The agent calls `evaluate`. Neither of them calls Ollama directly anymore.
  * **`OllamaProvider`** (default) — local Ollama in Docker at `OLLAMA_BASE_URL` (`http://localhost:11434`). Embeddings use `OLLAMA_EMBED_MODEL` (`nomic-embed-text`, 768 dimensions). Evaluation runs the Deep Agent on `ChatOllama` with `OLLAMA_CHAT_MODEL` (`llama3.2`) in JSON mode. If the Deep Agent transcript contains several JSON objects, the complete report is kept. The CV, requirements, and Tavily snippets sent to the model are shortened so they fit `llama3.2`'s context window. The same kinds of input are still sent. If that report is still invalid, the provider repeats the same Ollama `/api/chat` call in JSON mode, up to three times, including when a call does not finish. It does not send the full JSON schema to Ollama, because that grammar does not finish on this local model. Wording such as `not recommended` or a skill match of `yes` is read as the allowed values. The required report fields do not change.
  * **`MockLLMProvider`** — for development machines with no local Ollama. It makes no network call. `embed` returns a 768-dimension vector derived from a hash of the text, so the same text always gives the same vector. `evaluate` builds the report from the evidence alone: the score comes from `semantic_match`, and the skill breakdown comes from matching requirement keywords against `cv_text`.
  * **Selection:** `LLM_PROVIDER=ollama|mock`, default `ollama`. The agent never falls back to the mock on its own. If Ollama is down while `LLM_PROVIDER=ollama`, the evaluation fails and nothing is appended.
  * **No mixing:** Each Chroma vector stores the `embedding_provider` that made it in its metadata. Mock vectors and Ollama vectors are not comparable. After switching `LLM_PROVIDER`, rebuild `cv_embeddings` by replaying `ApplicationSubmitted` (Feature 4 replay).
* **Inputs:**
  * `application_id` from an `ApplicationSubmitted` event that has no `CandidateEvaluated` event yet.
  * Job `title` and `requirements` from the matching `JobCreated` event.
  * `full_name`, `email`, and plain `cv_text` from that `ApplicationSubmitted` event.
  * The CV vector already stored in Chroma collection `cv_embeddings` under that `application_id` (Feature 4).
* **Allowed access and tools:**
  * **Event Store (read):** `JobCreated` and `ApplicationSubmitted` only. The agent does not update or delete rows.
  * **Vector DB (read):** Chroma collection `cv_embeddings`. RAG embeds the job requirements with `LLMProvider.embed` and compares them with this candidate's stored vector. The agent does not upsert vectors.
  * **Tavily (via MCP only):** Web search to check industry standards for the job requirements and public details named in the CV. The agent calls the Feature 6 MCP tool. It never sends an HTTP request to Tavily itself.
  * **Write path:** The agent does not insert into the Event Store itself. It issues `EvaluateCandidateCommand`, and that command appends one `CandidateEvaluated` event.
* **Logic / actions, in order:**
  1. Select each `ApplicationSubmitted` event that has no later `CandidateEvaluated` for the same `application_id`, and whose job has no `JobClosed` event. Applications for a closed job are not a failure and are not retried.
  2. Load that job's requirements.
  3. RAG: query `cv_embeddings` with the job requirements and score the semantic match against this candidate's CV vector.
  4. Through MCP, run a Tavily search for current industry expectations of those requirements and for public facts the CV names. Do not invent sources.
  5. Call `LLMProvider.evaluate` with only the CV text, the job requirements, the RAG match, and the Tavily results. The provider returns the JSON report below.
  6. Validate the report. If a required key is missing, `status` is not one of the two allowed values, or `skill_breakdown` is empty, treat it as a model failure.
  7. Issue `EvaluateCandidateCommand`. If RAG, Tavily, the model call, or validation fails, append nothing. The application stays pending for the next run.
* **Expected output — evaluation report (JSON):**
  ```json
  {
    "status": "recommended",
    "score": 78,
    "skill_breakdown": [
      {"skill": "Python", "match": "met", "evidence": "5 years of Flask API work"},
      {"skill": "Kubernetes", "match": "missing", "evidence": ""}
    ],
    "strengths": "...",
    "weaknesses": "...",
    "missing_information": "...",
    "recommendation": "..."
  }
  ```
  * `status`: `recommended` or `not_recommended`.
  * `score`: the candidate match score, an integer from 0 to 100. Out-of-range values are clamped. A missing score, or a score of 0 while the breakdown has a met or partial skill, is replaced by the share of skills met (a partial skill counts as half).
  * `skill_breakdown`: one entry per skill named in the job requirements. `match` is `met`, `partial`, or `missing`. `evidence` quotes or paraphrases the CV and is empty when `match` is `missing`. This check reads the CV text. It does not use the embedding. When the model marks a skill missing but the CV names that skill, or a clear equivalent such as "team player" for teamwork, the skill is marked met and the CV sentence is the evidence. The score, status, and the four narrative fields are then rebuilt from that corrected breakdown. The HR page does the same for an assessment already saved, without rewriting the event.
  * `strengths`, `weaknesses`, `missing_information`, `recommendation`: the four fields Rule 4 requires. None may be empty. When the model leaves one blank, or writes a placeholder such as `None`, and the skill breakdown is present, that field is filled from the breakdown. Text the model did write is kept. The HR page applies the same fill when showing an assessment that was saved before this rule, without rewriting the event.
* **Expected output — event:**
  * One `CandidateEvaluated` event on aggregate type `Application`. Payload: the report above plus `application_id`, `job_id`, `email`, `semantic_match` (0–1 RAG similarity), `sources` (Tavily URLs), and `provider` (`ollama` or `mock`).
  * Events recorded before this change have no `skill_breakdown` or `provider`. The query model reads those as an empty breakdown and provider `ollama`. Old events are never rewritten.
  * The HR job drill-down shows that assessment beside the applicant's name, email, and CV text, including the skill breakdown as a table. An assessment with `provider` `mock` is labelled "Mock evaluation — not a real model judgement".
  * The HR accept or reject decision is Feature 7. This agent does not make that decision.
* **Tasks:**
  * Run the Deep Agent as an independent process.
  * Add the `LLMProvider` interface with `OllamaProvider` and `MockLLMProvider`, selected by `LLM_PROVIDER`.
  * Move the Feature 4 projector and the RAG query onto `LLMProvider.embed`, and stamp `embedding_provider` on each vector.
  * Implement the RAG query against `cv_embeddings`.
  * Call Tavily only through MCP.
  * Add `skill_breakdown` and `provider` to the report, its validation, and `EvaluateCandidateCommand`.
  * Command: `EvaluateCandidateCommand` -> append `CandidateEvaluated`.
  * Show the assessment and skill breakdown on the HR job drill-down.

## Feature 6: MCP Integration & Tools Definition
* **Goal:** Give the evaluation agent its external and data capabilities through MCP tools the project owns, and check in the Skill and Rule files that guide the agents.
* **MCP server:** One project MCP server, `screening-mcp`, built with MCP-Studio as the course requires. It runs over stdio and is started by the evaluation agent as a child process. Its source lives in `src/mcp_server/`. It is the only component that holds `TAVILY_API_KEY`.
* **Tool 1 — `web_search`:**
  * Input: `query` (string, required), `max_results` (integer, 1–10, default 5).
  * Action: calls the Tavily Search API with `TAVILY_API_KEY`. This is the only place in the system that sends HTTP to Tavily.
  * Output: a list of `{title, url, content}`.
  * Errors: a missing key, an empty query, or a Tavily failure returns an MCP error result. The agent then appends nothing (Feature 5 step 7).
  * Replaces the third-party `tavily-mcp` npm server the agent starts today.
* **Tool 2 — `semantic_cv_match`:**
  * Input: `application_id` (string, required), `requirements` (string, required).
  * Action: read-only. Embeds `requirements` with the configured `LLMProvider`, loads that application's vector from `cv_embeddings`, and returns the cosine similarity.
  * Output: `{application_id, semantic_match}` with `semantic_match` from 0 to 1.
  * Errors: no stored vector, or a provider mismatch with that vector's `embedding_provider`, returns an MCP error result.
  * Never writes to Chroma or the Event Store.
* **CQRS boundary:** Both tools are read-only. No MCP tool appends events. The only write path stays `EvaluateCandidateCommand`.
* **Configuration:** `TAVILY_API_KEY` in `.env`, documented in `.env.example`. A missing key makes `web_search` fail. It does not make the agent skip Tavily.
* **Skill and Rule files in the workspace:**
  * **Rule:** `.cursor/rules/sdad-cqrs.mdc`, always applied. It encodes Rule 1 (read the specs first, no ORM, no unapproved frameworks) and Rule 2 (commands only append, queries only read) from `rules.md` for the coding agent.
  * **Custom Skill:** `.cursor/skills/evaluate-candidate-fit/SKILL.md`. It follows the workflow in `skills.md`: load the pending application, call `semantic_cv_match`, call `web_search`, produce the Feature 5 JSON report, and issue `EvaluateCandidateCommand`.
  * **External Skill:** `tavily-research` from Skills.sh (`tavily-ai/skills`), installed with `npx skills add tavily-ai/skills --skill tavily-research` and kept at `.cursor/skills/tavily-research/SKILL.md`. `skills-lock.json` records its source and hash. It guides the coding agent's own research. It is not part of the evaluation agent's runtime, which reaches Tavily only through `web_search`.
* **Tasks:**
  * Build `screening-mcp` in MCP-Studio with `web_search` and `semantic_cv_match`.
  * Switch the agent from `tavily-mcp` and the in-process RAG query to these two tools.
  * Add the Rule file, the custom Skill file, and the Skills.sh skill.
  * Tests: each tool returns the documented output and errors, and neither tool appends events.

## Feature 7: HR Decision
* **Goal:** Let HR accept or reject one application after reading it. The evaluation agent never makes this decision.
* **Event:** `CandidateDecided` — aggregate type `Application`, same aggregate id as `ApplicationSubmitted`. Payload: `application_id`, `job_id`, `decision` (`accepted` or `rejected`), `decided_by` (the logged-in HR email). Appended by `DecideCandidateCommand`.
* **Validation, before any write:**
  * `decision` must be `accepted` or `rejected`. `decided_by` must be present.
  * The `application_id` must already have an `ApplicationSubmitted` event. The command copies that event's `job_id` into the payload.
  * A stream that already contains `CandidateDecided` is rejected. HR cannot change the decision. The event row is never updated or deleted.
  * A decision does not require a `CandidateEvaluated` event. HR may decide while the assessment is still pending.
* **UI:**
  * The candidate page (`GET /hr/applications/<application_id>`) shows Accept and Reject when there is no decision yet. `POST /hr/applications/<application_id>/decision` runs the command. A candidate account gets 403.
  * After a decision, the buttons are gone. The page, the job's applicant row, and the HR search results show `accepted` or `rejected`, and the page also shows `decided_by`.
  * The candidate dashboard is unchanged. A decided application still shows Applied.
* **Tasks:**
  * Command: `DecideCandidateCommand` -> append `CandidateDecided`.
  * Replay `CandidateDecided` in the HR job drill-down, the candidate page, and HR search.
  * Accept and Reject on the candidate page only. The evaluation agent does not issue this command.