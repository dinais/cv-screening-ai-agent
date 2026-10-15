# System Architecture: Candidate Screening System

## 1. Architectural Overview
The system is built as a modular web application driven by a Flask backend[cite: 1]. It strictly separates read and write operations using the CQRS (Command Query Responsibility Segregation) pattern[cite: 1] and tracks state changes using Event Sourcing[cite: 1]. An independent AI Agent subsystem interacts with the application to evaluate candidates asynchronously[cite: 1].

## 2. Core Technologies
* **Backend Framework:** Python with Flask[cite: 1].
* **Relational Database / Cloud:** Cloud-hosted SQL database (e.g., Somee.com) for event persistence[cite: 1].
* **Vector Database:** ChromaDB, persisted at `VECTOR_DB_PATH`. Each CV embedding is produced from the plain `cv_text` on an `ApplicationSubmitted` event through `LLMProvider.embed` (section 3.4). By default that is local Ollama (`ollama + Docker`) at `http://localhost:11434` with the model `nomic-embed-text`.
* **AI Infrastructure:** Deep Agent framework running as a separate process. HR starts it from the dashboard with `python -m src.agents` for every pending application, or `python -m src.agents --job-id <job_id>` for one job. The web request does not evaluate. Model calls go through `LLMProvider`. The default `OllamaProvider` uses local Ollama in Docker (`llama3.2` for evaluation, `nomic-embed-text` for embeddings). `MockLLMProvider` covers development machines with no Ollama. No OpenAI call.
* **Integration Protocol:** MCP (Model Context Protocol) for all external tools. The project MCP server `screening-mcp` (built with MCP-Studio) exposes `web_search` (Tavily) and `semantic_cv_match` (section 4.1).

## 3. Design Patterns & Application Structure
### 3.1. MVC & CQRS Pattern
The application follows a strict CQRS organization as depicted in the system diagram[cite: 1]:
* **UI / Presentation:** The frontend layer where the user makes a change[cite: 1].
* **API Gateway / Routing:** Routes change information to the Command Model[cite: 1].
* **Command Model (Write):** Executes validations and consequential business logic[cite: 1]. It handles user actions (e.g., "Submit Application", "Create Job") and updates the database[cite: 1].
* **Query Model (Read):** Reads from the database to populate the UI (e.g., Dashboard, Candidates List)[cite: 1]. It does not modify data. HR search (`GET /hr/?q=`) and the single-application drill-down (`GET /hr/applications/<application_id>`) are queries over the same replayed state. The dashboard opens job creation in a dialog that still posts to `POST /hr/jobs`. Applicant tables show a truncated CV and an assessment badge. View expands the job or the full application on the same page; a second click collapses it. New tab and the assessment badge still open the drill-down page and the slide-over.

### 3.2. Event Sourcing
Instead of storing only the current state of an entity (e.g., Candidate status = "Evaluated"), the relational database acts as an Append-Only Event Store[cite: 1]. 
* Every state change is saved as an immutable event (e.g., `JobCreated`, `JobClosed`, `ApplicationSubmitted`, `CandidateEvaluated`, `CandidateDecided`). Closing a job appends `JobClosed`. It does not delete `JobCreated`. Replay then treats that job as Closed: it leaves the open dashboards, and the evaluation agent does not select its applications.
* The current state of a job or a candidate is derived by replaying these events.

### 3.3. CV Embedding Projection
`cv_text` lives on the append-only `ApplicationSubmitted` event. It is the text extracted from the candidate's PDF before the command runs. Words that the PDF places on separate lines are joined into sentences first. The PDF file is saved at `data/cvs/<application_id>.pdf` after the event is committed. It is not an event payload. HR opens that file through `GET /hr/applications/<application_id>/cv`. The command does not write to the vector store and does not call a model. After the event is committed, a projector reads that `cv_text`, gets an embedding from `LLMProvider.embed`, and upserts it into the Chroma collection `cv_embeddings`. The vector id is `application_id`. The metadata records `embedding_provider` (`ollama` or `mock`). Rebuilding the collection reads the same events again and does not modify the Event Store.

### 3.4. LLM Provider Abstraction
All model access goes through one interface, so the agent and the projector do not depend on Ollama being installed.

| Operation | Used by | `OllamaProvider` | `MockLLMProvider` |
|---|---|---|---|
| `embed(text) -> list[float]` | CV projector, `semantic_cv_match` | Ollama `/api/embed`, `nomic-embed-text`, 768 dimensions | Deterministic 768-dimension hash vector, no network |
| `evaluate(evidence) -> dict` | Evaluation agent | Deep Agent on `ChatOllama` (`llama3.2`, JSON mode, context trimmed to the 4096-token window). If that report is invalid or the call does not finish, the same Ollama `/api/chat` call in JSON mode is repeated up to three times | Report derived from `semantic_match` and requirement-keyword overlap with `cv_text` |

* **Selection:** `LLM_PROVIDER=ollama|mock`, read once at process start. Default `ollama`. There is no automatic fallback from Ollama to the mock.
* **Isolation:** Vectors from different providers are never compared. A query whose provider differs from a vector's `embedding_provider` fails instead of returning a score. After switching provider, rebuild `cv_embeddings` by replay.
* **Traceability:** Every `CandidateEvaluated` event records `provider`. HR sees mock evaluations labelled as mock.

## 4. AI Subsystem: Candidate Evaluation Agent
The evaluation agent is a Deep Agent process. It is not part of the Flask request cycle, so a running evaluation does not block sign-in, job creation, or applications.
* **Independent process:** A separate operating-system process. Flask only displays results that are already stored as events.
* **Model:** `LLMProvider.evaluate` (section 3.4). Default is local Ollama in Docker (`http://localhost:11434`). No OpenAI call.
* **Inputs:** An `ApplicationSubmitted` event with no `CandidateEvaluated` yet, the matching job requirements, and that application's vector in Chroma.
* **RAG:** Through the MCP tool `semantic_cv_match`, the agent compares the candidate's CV vector with the embedded job requirements. Nothing is written to Chroma.
* **Web search:** Through the MCP tool `web_search`. The agent does not call the Tavily HTTP API itself and does not hold `TAVILY_API_KEY`.
* **Pipeline:** select pending application → `semantic_cv_match` → `web_search` → `LLMProvider.evaluate` → validate report → `EvaluateCandidateCommand`. Any failure stops that application before the command, so nothing is appended and it is retried on the next run.
* **Write boundary:** The agent issues `EvaluateCandidateCommand`. That command appends one `CandidateEvaluated` event and does not update or delete earlier events.
* **Output:** A structured JSON report: `status`, `score` (0–100 match score), `skill_breakdown` (per required skill: `met`, `partial`, or `missing`, with CV evidence), `strengths`, `weaknesses`, `missing_information`, and `recommendation`. The event adds `semantic_match`, `sources`, and `provider`. HR's later accept or reject is `DecideCandidateCommand`, which appends one `CandidateDecided` event (`accepted` or `rejected`). The agent does not issue that command. A second decision is rejected.

### 4.1. MCP Server and Tools
`screening-mcp` is a project-owned MCP server built with MCP-Studio. Its source is in `src/mcp_server/`. The evaluation agent starts it as a stdio child process.

| Tool | Input | Output | Reads | Writes |
|---|---|---|---|---|
| `web_search` | `query`, `max_results` (1–10, default 5) | `[{title, url, content}]` | Tavily Search API with `TAVILY_API_KEY` | Nothing |
| `semantic_cv_match` | `application_id`, `requirements` | `{application_id, semantic_match}` | Chroma `cv_embeddings`, `LLMProvider.embed` | Nothing |

* `screening-mcp` is the only process that holds `TAVILY_API_KEY` and the only one that sends HTTP to Tavily. That keeps the agent within Rule 3.
* Both tools are read-only, so the CQRS write path stays `EvaluateCandidateCommand` alone.
* A tool failure comes back as an MCP error result, never as an empty success.

### 4.2. Agent Guidance Files
* **Rule:** `.cursor/rules/sdad-cqrs.mdc` puts Rules 1 and 2 from `rules.md` in front of the coding agent on every request.
* **Custom Skill:** `.cursor/skills/evaluate-candidate-fit/SKILL.md`, the evaluation workflow from `skills.md`.
* **External Skill:** `tavily-research` from Skills.sh (`tavily-ai/skills`), at `.cursor/skills/tavily-research/SKILL.md`, with its source pinned in `skills-lock.json`. It is for the coding agent only. The evaluation agent still reaches Tavily only through `web_search`.

## 5. System Components Diagram Map
Based on the provided specification[cite: 1]:
1. **Candidate Screening System (Flask App):** Manages the UI, API Gateway, Query Model, and Command Model.
2. **Cloud Database (Somee.com):** Hosts the Event Store.
3. **Vector DB (ChromaDB):** Stores one embedding per `ApplicationSubmitted` event. The embedding comes from `LLMProvider.embed` (local Ollama `nomic-embed-text` by default) applied to `cv_text`.
4. **Deep Agent Process:** The Candidate Evaluation Agent. Independent of Flask. Judges fit through `LLMProvider`, gets RAG and web search from `screening-mcp`, and appends `CandidateEvaluated` through the command model.
5. **LLM Provider:** `OllamaProvider` (Ollama in Docker: `llama3.2`, `nomic-embed-text`) or `MockLLMProvider`, selected by `LLM_PROVIDER`.
6. **MCP Server (`screening-mcp`):** Project-owned, built with MCP-Studio. Tools `web_search` (Tavily) and `semantic_cv_match` (Chroma). Read-only.