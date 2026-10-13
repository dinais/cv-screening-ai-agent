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
  * **Application:** One candidate's submission for one job. The candidate is the logged-in account, identified by email. Login accounts stay the mock users from Feature 1.
* **Events:**
  * `JobCreated` — aggregate type `Job`. Payload: `job_id`, `title`, `requirements`, `created_by`. Appended by `CreateJobCommand` when HR submits the new-job form. A missing title or missing requirements is rejected before any database write.
  * `ApplicationSubmitted` — aggregate type `Application`. Payload: `application_id`, `job_id`, `full_name`, `email`, `cv_text`. Appended by `SubmitApplicationCommand` when a candidate submits the form for one job. `cv_text` is plain text. A missing name, a missing job, or an unknown job is rejected before any database write. Before appending, the command reads existing `ApplicationSubmitted` events and rejects the command when this email has already applied to this `job_id`. That rejection also happens before any database write. Embeddings are Feature 4.
* **Query Model:**
  * The read side loads `JobCreated` and `ApplicationSubmitted` from the Event Store in order and replays them. It does not update or delete rows.
  * Each `JobCreated` becomes an open job with status Open.
  * Each `ApplicationSubmitted` is attached to that job, increases its applicant count, and records that applicant's `full_name`, `email`, and `cv_text`.
  * The HR dashboard shows the open-job count, the total applicant count, and a table with each job's status and applicant count.
  * The HR job drill-down shows the requirements, the applicant count, and the list of applicants (`full_name`, `email`, and `cv_text`).
  * The candidate dashboard lists the same open jobs. The query takes the logged-in candidate's email. A job with no `ApplicationSubmitted` for that email is marked not applied. A job that already has one is marked applied.
* **Tasks:**
  * HR form to create a job, the jobs table, and the drill-down fed by the projection.
  * Candidate dashboard: each open job shows an Apply action, or an Applied indicator when this candidate has already applied. There is no generic job dropdown.
  * Apply action opens a form for that job only. The form collects the candidate's name and `cv_text`. After a successful submit, the candidate returns to the dashboard and that job shows Applied.
  * Command: `CreateJobCommand` -> append `JobCreated`.
  * Command: `SubmitApplicationCommand` -> append `ApplicationSubmitted`, or reject a duplicate application for the same email and `job_id`.
  * Query: replay the events into the HR dashboard, the HR applicant list, and the candidate dashboard.

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
  * Searching those vectors against a job's requirements is Feature 7.

## Feature 5: Dashboard and Data Display
* **Goal:** Show the Feature 3 projection on the HR dashboard[cite: 1].
* **Tasks:**
  * The open-job count, the applicant count, and the per-job applicant totals are produced by the Feature 3 query model[cite: 1].
  * Display that projection in the dashboard table and the job drill-down[cite: 1].

## Feature 6: MCP Integration & Tools Definition
* **Goal:** Set up the Model Context Protocol (MCP) and define required tools[cite: 1].
* **Tasks:**
  * Use MCP-Studio to develop at least two custom MCP Tools[cite: 1].
  * Integrate external services via MCP (e.g., Tavily.com for search, Gmail for notifications)[cite: 1].
  * Define and implement at least one custom Skill and one external Skill from Skills.sh[cite: 1].
  * Define the AI Rule(s)[cite: 1].

## Feature 7: Deep Agent Integration (Job Fit Assessment)
* **Goal:** Implement the independent AI Agent process to evaluate candidates[cite: 1].
* **Tasks:**
  * Set up the Deep Agent infrastructure (running as an independent process)[cite: 1].
  * Implement semantic search (RAG) querying the Vector DB against job requirements[cite: 1].
  * Implement web search capability via Tavily.com tool[cite: 1].
  * Generate an evaluation report and issue an `EvaluateCandidateCommand` to update the DB[cite: 1].
  * Update HR UI to view the AI Agent's evaluation and accept/reject the candidate[cite: 1].