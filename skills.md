# AI Skills Definition: Candidate Screening System

This document maps the specific Skills the Job Fit Assessment Agent possesses to complete its tasks[cite: 1].

## 1. External Skill (from Skills.sh)
As per the requirement to use at least one external skill from Skills.sh[cite: 1]:
* **Skill Name:** `tavily-research` (or equivalent external search/research skill).
* **Description:** Empowers the agent to perform deep web research to evaluate a candidate's background, verify past employers, or research the required tech stack for the job[cite: 1].
* **Usage:** Triggered when the job description contains domain-specific requirements the agent needs to understand better, or to verify a candidate's public portfolio.

## 2. Custom Skill (System Specific)
As per the requirement to define at least one custom skill[cite: 1]:
* **Skill Name:** `evaluate-candidate-fit`
* **Description:** The core business-logic workflow for the Job Fit Assessment Agent[cite: 1].
* **Workflow Steps:**
  1. Retrieve Candidate ID and Job ID.
  2. Execute a Semantic Search (RAG) querying the Vector DB to compare the candidate's CV embeddings with the job requirements[cite: 1].
  3. Use the MCP Tool to perform a Web Search (Tavily) to gather current industry standards regarding the job requirements[cite: 1].
  4. Synthesize the findings.
  5. Formulate a JSON-formatted evaluation report (Status, Score, Reasoning).
  6. Emit an `EvaluateCandidateCommand` to update the Event Store.