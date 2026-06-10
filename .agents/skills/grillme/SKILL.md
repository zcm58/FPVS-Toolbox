---
name: grillme
description: Use when the user asks Codex to grill, interrogate, pressure-test, or relentlessly interview them about a plan, design, architecture, implementation approach, product idea, research plan, migration, or decision tree until there is a shared understanding. The skill asks one question at a time, recommends an answer for each question, resolves dependencies between decisions, and explores the codebase instead of asking questions that local inspection can answer.
---

# Grill Me

## Overview

Use this skill to turn a vague or high-stakes plan into a shared, explicit design. Be persistent, specific, and constructive: walk the design tree branch by branch, resolve dependencies in order, and keep questioning until the remaining ambiguity is intentional.

## Workflow

1. Restate the plan briefly in your own words, including any assumptions already visible from the user's message or the codebase.
2. Identify the next most important unresolved decision. Prefer decisions that block other choices.
3. If the answer can be discovered by inspecting local files, commands, docs, tests, config, or repository history, explore the codebase instead of asking the user.
4. Ask exactly one question.
5. Include your recommended answer immediately after the question, with a concise reason.
6. Wait for the user's answer before asking the next question.
7. After each answer, update the shared understanding and choose the next dependency-aware branch of the design tree.
8. Continue until the plan has clear goals, constraints, dependencies, implementation shape, risks, validation, rollout, and ownership.

## Question Style

- Ask concrete questions that force a decision, not broad prompts.
- Prefer "Should we choose A or B?" over "What do you think?"
- Include the tradeoff that makes the question matter.
- Do not bundle multiple decisions into one question.
- Do not ask the user to confirm facts that are discoverable from the workspace.
- Keep the tone direct and collaborative, not performatively harsh.

Use this format:

```markdown
My read so far: ...

Question: ...

Recommended answer: ...
```

## Codebase Exploration

When the plan concerns an existing repository:

- Inspect the smallest relevant set of files, docs, tests, config, and history before asking about existing behavior.
- Use fast searches and targeted file reads.
- Treat current code, tests, and docs as evidence, then ask only about preferences, intent, constraints, or tradeoffs that remain unknown.
- Summarize discovered facts briefly before the question when they affect the recommended answer.

## Completion Criteria

Stop grilling only when these are clear enough to act on:

- Objective and non-goals
- Users, stakeholders, and success criteria
- Constraints, dependencies, and sequencing
- Key design choices and rejected alternatives
- Data, API, UI, migration, testing, rollout, and observability implications when relevant
- Risks, failure modes, and rollback or recovery path
