# System Architecture: Candidate Screening System

## 1. Architectural Overview
The system is built as a modular web application driven by a Flask backend[cite: 1]. It strictly separates read and write operations using the CQRS (Command Query Responsibility Segregation) pattern[cite: 1] and tracks state changes using Event Sourcing[cite: 1]. An independent AI Agent subsystem interacts with the application to evaluate candidates asynchronously[cite: 1].

## 2. Core Technologies
* **Backend Framework:** Python with Flask[cite: 1].
* **Relational Database / Cloud:** Cloud-hosted SQL database (e.g., Somee.com) for event persistence[cite: 1].
* **Vector Database:** A vector store (e.g., ChromaDB, FAISS, or similar) to store CV embeddings for semantic search and RAG[cite: 1].
* **AI Infrastructure:** Deep Agent framework running as a separate process (optionally using Ollama + Docker)[cite: 1].
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

## 4. AI Subsystem: Job Fit Assessment Agent
The AI evaluation mechanism operates independently from the main web server to avoid blocking user interactions:
* **Independent Process:** The agent runs as a separate background process[cite: 1].
* **Data Ingestion:** It reads job requirements and candidate data (CVs) from the database[cite: 1].
* **RAG & Semantic Search:** CVs are embedded and queried using the Vector Database to find semantic matches against job requirements[cite: 1].
* **External Tools:** It uses MCP-Studio generated tools and external MCP servers (like Tavily for web search or Gmail for notifications)[cite: 1].
* **Feedback Loop:** Once the evaluation is complete, the Agent sends a command to the Command Model to update the database with the assessment results.

## 5. System Components Diagram Map
Based on the provided specification[cite: 1]:
1. **Candidate Screening System (Flask App):** Manages the UI, API Gateway, Query Model, and Command Model.
2. **Cloud Database (Somee.com):** Hosts the Event Store.
3. **Vector DB:** Handles CV embeddings.
4. **Deep Agent Process:** The Job Fit Assessment Agent.
5. **MCP Servers:** Connects the Agent to external capabilities (Tavily, Gmail)[cite: 1].