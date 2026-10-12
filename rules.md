# AI Rules & Constraints: Candidate Screening System

This document defines the mandatory rules for any AI agent interacting with or operating within the system[cite: 1].

## Rule 1: SDAD Strict Compliance
* **Context:** When acting as a development assistant (e.g., Cursor Agent).
* **Instruction:** You must read `requirements.md` and `architecture.md` before writing or modifying any application code. Never introduce new frameworks, ORMs (like SQLAlchemy), or design patterns without explicit user approval. 

## Rule 2: CQRS & Event Sourcing Integrity
* **Context:** When implementing backend services[cite: 1].
* **Instruction:** Commands must only append events to the Event Store and never return domain data[cite: 1]. Queries must only read from the database to present data and never modify the state[cite: 1].

## Rule 3: MCP-Only External Communication
* **Context:** When the Job Fit Assessment Agent needs external data[cite: 1].
* **Instruction:** The Agent is strictly forbidden from making direct HTTP requests to external APIs (e.g., Tavily, Google Workspace). All external communication must be routed through the Model Context Protocol (MCP) using defined Tools[cite: 1].

## Rule 4: Objective Candidate Evaluation
* **Context:** The Job Fit Assessment Agent evaluating a CV[cite: 1].
* **Instruction:** The evaluation report must strictly rely on data found in the CV (Vector DB via RAG) and verified industry standards (Tavily Search)[cite: 1]. The agent must output a structured assessment detailing: [Strengths, Weaknesses, Missing Information, Final Recommendation].