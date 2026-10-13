# System Architecture: Candidate Screening System

## 1. Architectural Overview
The system is built as a modular web application driven by a Flask backend[cite: 1]. It strictly separates read and write operations using the CQRS (Command Query Responsibility Segregation) pattern[cite: 1] and tracks state changes using Event Sourcing[cite: 1]. An independent AI Agent subsystem interacts with the application to evaluate candidates asynchronously[cite: 1].

## 2. Core Technologies
* **Backend Framework:** Python with Flask[cite: 1].
* **Relational Database / Cloud:** Cloud-hosted SQL database (e.g., Somee.com) for event persistence[cite: 1].
* **Vector Database:** ChromaDB, persisted at `VECTOR_DB_PATH`. Each CV embedding is produced by a local Ollama server (`ollama + Docker`) from the plain `cv_text` on an `ApplicationSubmitted` event. Ollama listens at `http://localhost:11434` and uses the model `nomic-embed-text`.
* **AI Infrastructure:** Deep Agent framework running as a separate process. Local model calls use Ollama in Docker, not OpenAI.
* **Integration Protocol:** MCP (Model Context Protocol) for all external tools (e.g., Tavily, Gmail)[cite: 1].

## 3. Design Patterns & Application Structure
### 3.1. MVC & CQRS Pattern
The application follows a strict CQRS organization as depicted in the system diagram[cite: 1]:
* **UI / Presentation:** The frontend layer where the user makes a change[cite: 1].
* **API Gateway / Routing:** Routes change information to the Command Model[cite: 1].
* **Command Model (Write):** Executes validations and consequential business logic[cite: 1]. It handles user actions (e.g., "Submit Application", "Create Job") and updates the database[cite: 1].
* **Query Model (Read):** Reads from the database to populate the UI (e.g., Dashboard, Candidates List)[cite: 1]. It does not modify data.

### 3.2. Event Sourcing
Instead of storing only the current state of an entity (e.g., Candidate status = "Evaluated"), the relational database acts as an Append-Only Event Store[cite: 1]. 
* Every state change is saved as an immutable event (e.g., `JobCreated`, `ApplicationSubmitted`, `CandidateEvaluated`).
* The current state of a job or a candidate is derived by replaying these events.

### 3.3. CV Embedding Projection
`cv_text` lives on the append-only `ApplicationSubmitted` event. The command does not write to the vector store and does not call Ollama. After the event is committed, a projector reads that `cv_text`, requests an embedding from the local Ollama server required by the course architecture (`ollama + Docker`, `http://localhost:11434`, model `nomic-embed-text`), and upserts it into the Chroma collection `cv_embeddings`. The vector id is `application_id`. Rebuilding the collection reads the same events again and does not modify the Event Store.

## 4. AI Subsystem: Candidate Evaluation Agent
The evaluation agent is a Deep Agent process. It is not part of the Flask request cycle, so a running evaluation does not block sign-in, job creation, or applications.
* **Independent process:** A separate operating-system process. Flask only displays results that are already stored as events.
* **Model:** Local Ollama in Docker (`http://localhost:11434`). No OpenAI call.
* **Inputs:** An `ApplicationSubmitted` event with no `CandidateEvaluated` yet, the matching job requirements, and that application's vector in Chroma.
* **RAG:** The agent reads `cv_embeddings` and compares the CV vector with the job requirements. It does not write to Chroma.
* **Web search:** Tavily is reached only through MCP. The agent does not call the Tavily HTTP API itself.
* **Write boundary:** The agent issues `EvaluateCandidateCommand`. That command appends one `CandidateEvaluated` event and does not update or delete earlier events.
* **Output:** `status`, `score`, strengths, weaknesses, missing information, recommendation, semantic match, and sources. HR's later accept or reject is a different command.

## 5. System Components Diagram Map
Based on the provided specification[cite: 1]:
1. **Candidate Screening System (Flask App):** Manages the UI, API Gateway, Query Model, and Command Model.
2. **Cloud Database (Somee.com):** Hosts the Event Store.
3. **Vector DB (ChromaDB):** Stores one embedding per `ApplicationSubmitted` event. The embedding is produced by local Ollama (`ollama + Docker`) from `cv_text`.
4. **Deep Agent Process:** The Candidate Evaluation Agent. Independent of Flask. Uses Ollama, reads Chroma for RAG, calls Tavily through MCP, and appends `CandidateEvaluated` through the command model.
5. **MCP Servers:** Connects the Agent to external capabilities (Tavily, Gmail)[cite: 1].