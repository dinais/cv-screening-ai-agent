---
name: evaluate-candidate-fit
description: Evaluate how well a submitted candidate fits a job in the Candidate Screening System, using RAG over the CV vector and Tavily web search through the screening-mcp server. Use when asked to evaluate, score, or assess candidates, or to run or debug the evaluation agent.
---

# Evaluate candidate fit

## Run it
```powershell
python -m src.agents
```
The process evaluates every `ApplicationSubmitted` event that has no `CandidateEvaluated` yet. `LLM_PROVIDER` in `.env` chooses `ollama` or `mock`.

## Workflow (one application)
1. Load the application (`application_id`, `job_id`, `full_name`, `email`, `cv_text`) and its job's `title` and `requirements` from the Event Store. Read only.
2. Call the MCP tool `semantic_cv_match` with `application_id` and `requirements`. It returns `semantic_match` from 0 to 1.
3. Call the MCP tool `web_search` twice: once for current industry expectations of the requirements, once for public facts the CV names. Keep the result URLs as `sources`. Never invent a source.
4. Call `LLMProvider.evaluate` with the CV text, requirements, `semantic_match`, and the search results. It returns:
   ```json
   {
     "status": "recommended | not_recommended",
     "score": 0,
     "skill_breakdown": [{"skill": "", "match": "met | partial | missing", "evidence": ""}],
     "strengths": "",
     "weaknesses": "",
     "missing_information": "",
     "recommendation": ""
   }
   ```
5. Validate with `require_report` (`src/providers/report.py`). An incomplete report, or an empty `skill_breakdown`, is a failure.
6. Issue `EvaluateCandidateCommand` with the report, `semantic_match`, `sources`, and the provider name.

## Failure rule
If any step fails, issue no command. The application stays pending and is retried on the next run.

## Do not
- Write to the Event Store or Chroma directly.
- Call Tavily or any external API without going through `screening-mcp`.
- Accept or reject the candidate. That decision belongs to HR.
