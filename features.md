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

## Feature 3: Job Management (HR Persona)
* **Goal:** Allow HR to manage job postings[cite: 1].
* **Tasks:**
  * UI form for HR to input job requirements[cite: 1].
  * Command: `CreateJobCommand` -> Append `JobCreated` event.
  * Query: Read job events to display the jobs list and drill-down details[cite: 1].

## Feature 4: Candidate Application & Vector DB Integration
* **Goal:** Allow candidates to apply and store their CVs in the Vector DB[cite: 1].
* **Tasks:**
  * UI form for Candidates to submit CVs and apply for jobs[cite: 1].
  * Integrate Vector DB (e.g., ChromaDB).
  * Convert CV text into embeddings and store them[cite: 1].
  * Command: `SubmitApplicationCommand` -> Append `ApplicationSubmitted` event.

## Feature 5: Dashboard and Data Display
* **Goal:** Provide the required system dashboard[cite: 1].
* **Tasks:**
  * Implement Dashboard UI[cite: 1].
  * Query Model: Aggregate data to show the status of open jobs and the number of registered applicants per job[cite: 1].
  * Display data in a structured table[cite: 1].

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