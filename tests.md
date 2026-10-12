# Testing Strategy: Candidate Screening System

This document outlines the testing strategy for the Candidate Screening System, ensuring that all functional, architectural, and AI-related requirements are met[cite: 1].

## 1. Authentication & Authorization Tests
* **Normal Case:** HR manager logs in and sees the HR dashboard; Candidate logs in and sees the job list.
* **Edge Case/Invalid:** Unauthenticated user attempts to access a protected route (e.g., submitting a job or viewing the dashboard). Should redirect to login.
* **Role Verification:** A Candidate attempts to access the HR route to evaluate candidates. Should return a 403 Forbidden.

## 2. CQRS & Event Sourcing Integrity
* **Command Testing:** When an HR manager creates a job, verify that a `JobCreated` event is successfully appended to the Event Store (Somee.com cloud DB)[cite: 1].
* **Query Testing:** Verify that the Query Model reconstructs the current state correctly from the Event Store without modifying any data[cite: 1].
* **Error Handling:** Attempt to append an event with missing mandatory fields. The Command handler should reject it before interacting with the database.

## 3. Vector Database & RAG
* **Embedding Creation:** Verify that when a candidate uploads a CV, the text is successfully converted into vector embeddings and stored in the Vector DB[cite: 1].
* **Semantic Match:** Search for a specific software engineering skill (e.g., "Python Backend") and verify that a CV containing "Flask API development" ranks highly[cite: 1].

## 4. AI Agent: Job Fit Assessment (Deep Agent)
* **Normal Case:** The Agent receives a CV and a Job Description, successfully queries the Vector DB (RAG), searches Tavily for tech stack verification, and produces a valid JSON evaluation report[cite: 1].
* **Tool Behavior (MCP):** Verify that the Agent exclusively uses MCP Tools for external calls (e.g., Tavily, Gmail)[cite: 1]. Attempt to run the agent without internet access to verify error handling.
* **Edge Case (Unrelated CV):** Feed the Agent a CV of a chef for a Senior Developer position. Verify that the Agent correctly rejects the candidate with a low score and clear reasoning.
* **Final Output:** Verify that the Agent successfully issues an `EvaluateCandidateCommand` that updates the Event Store with the final assessment[cite: 1].

## 5. UI/Dashboard
* **Dashboard Data:** Verify that the dashboard accurately reflects the number of open jobs and the exact number of candidates applied per job[cite: 1].
* **Drill-down:** Click on a specific candidate row in the table and verify that the full application details (and AI evaluation) are displayed correctly[cite: 1].