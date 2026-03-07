---
name: review-pr
description: Thoroughly review a pull request
---

# Review PR <number>

1. Fetch PR diff: `gh pr diff <number>`
2. Fetch PR details: `gh pr view <number> --json title,body,files,reviews`
3. Analyze:
   - Correctness of the implementation
   - Test coverage (are there tests for the changes?)
   - Code style (ruff/mypy strict compliance, type hints on all public functions)
   - HA conventions (async def for I/O, proper entity inheritance)
   - Potential bugs or edge cases (e.g. sensor resets, negative prices, VAT handling)
   - Breaking changes (config entry schema changes need migration)
4. Write review comments as a markdown list
5. Post comments via: `gh pr review <number> --comment --body "<your review>"`
