# Requirements Specification: Candidate Screening System

## 1. System Overview
The system is an AI-powered Candidate Screening and Evaluation platform, developed following Specification-Driven Application Development (SDAD) principles[cite: 1]. 
It allows HR personnel to post job requirements and candidates to apply by submitting their CVs[cite: 1]. An autonomous AI Agent evaluates the candidates' suitability for the job using semantic search, RAG, and web search, assisting HR in making informed decisions[cite: 1].

## 2. User Roles
The system must support authentication and at least two types of users[cite: 1]:
* **HR Manager:** Can input job requirements, view the list of candidates, read AI evaluations, and make final accept/reject decisions[cite: 1].
* **Candidate:** Can view open positions and submit a job application along with a CV[cite: 1].

## 3. Functional Requirements
1. **Authentication:** The system must manage users and require authentication upon login[cite: 1].
2. **Data Entry:** Support data entry workflows, specifically HR creating jobs and candidates applying for them[cite: 1].
3. **Data Retrieval & Display:** 
   * Search functionality for existing records[cite: 1].
   * Tabular display of data (e.g., list of candidates)[cite: 1].
   * Detailed drill-down view for a specific record[cite: 1].
4. **Dashboard:** A main dashboard must display the status of open jobs and the number of applicants registered for each job[cite: 1].
5. **UI/UX:** The user interface must be professional, aesthetic, and follow standard UI/UX principles[cite: 1].

## 4. AI Agent Requirements (Job Fit Assessment Agent)
1. **Execution:** The agent must run as an independent process based on the Deep Agent infrastructure[cite: 1].
2. **Evaluation Workflow:** The agent will read candidate and job records from the database[cite: 1] and run a series of checks, including:
   * **Web Search:** Utilizing tools like Tavily.com to verify or expand candidate/domain information[cite: 1].
   * **RAG (Retrieval-Augmented Generation):** Consulting a vector database to evaluate the candidate's CV against the job requirements[cite: 1].
3. **Output:** The agent will produce an evaluation report and recommendation (status) for the HR manager[cite: 1].

## 5. Non-Functional & Architectural Requirements
1. **Code Management:** All code and SDAD documents must be managed in a GitHub Repository[cite: 1].
2. **Backend:** The application server must be developed using the Flask framework[cite: 1].
3. **Architecture Patterns:** The application services must be strictly organized using MVC and CQRS patterns[cite: 1].
4. **Data Persistence & Event Sourcing:** Data must be saved in a cloud database (e.g., Somee.com) implementing the Event Sourcing pattern[cite: 1].
5. **Vector Database:** Candidate CVs must undergo embedding and be stored in a Vector Database to enable semantic search for matching candidates to jobs[cite: 1].

## 6. Integrations, Tools, and Rules
1. **MCP Integration:** Potential external services (e.g., Tavily.com, Gmail MCP) must be consumed via the Model Context Protocol (MCP)[cite: 1].
2. **Custom MCP Tools:** At least two dedicated MCP Tools must be developed using MCP-Studio[cite: 1].
3. **Skills:**
   * At least one existing Skill must be utilized from Skills.sh[cite: 1].
   * At least one custom Skill must be defined[cite: 1].
4. **Rules:** At least one custom Rule must be defined to guide the AI agent or development process[cite: 1].