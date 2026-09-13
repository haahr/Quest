# Tool Discipline & Anti-Looping Rules

## 1. No Duplicate File Reads
- NEVER call `view_file` on the same file with identical or overlapping line ranges within the same task or turn.
- If a file chunk has been inspected earlier in the conversation or current turn, use the content already present in context.

## 2. Inspection Cap & Distinct Targets
- Limit consecutive read-only tool calls (`view_file`, `grep_search`, `find_by_name`, `list_dir`) to a MAXIMUM of 10 before taking action (e.g., editing a file, executing a verification command, or responding).
- Every inspection call in a chain MUST target distinct information or distinct files; visiting any previously-read range or oscillating between files is strictly prohibited and must immediately terminate the inspection chain.
- If an answer is not found after 10 distinct inspections, STOP inspecting: formulate a targeted python/shell one-liner test, apply the best hypothesis with an edit, or communicate directly.

## 3. Quota and Efficiency Prioritization
- Never poll or oscillate between files trying to double-check already known facts.
- Avoid repetitive tool loops at all costs to preserve context window space and user quota.
