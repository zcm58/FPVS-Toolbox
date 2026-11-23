---
name: grillme
description: Pressure-test a plan through a requested interview. Resolve one decision at a time and recommend an answer grounded in the available evidence.
---

# Grill Me

Use this interview when the user asks to pressure-test a plan. The interview
resolves decisions and records the agreed scope.

1. Briefly state the intended outcome and the assumptions that affect the next
   decision.
2. Resolve facts from relevant code, tests, contracts, or history. For Toolbox,
   start with the [agent index](../../../docs/agent/agent-index.md), the owning
   [architecture](../../../ARCHITECTURE.md), and any matching
   [active plan](../../../docs/agent/exec-plans/README.md). Trace the current
   entry point and separate implemented behavior from planned work.
3. Ask one concrete question about an unresolved choice that affects dependent
   decisions. Give your recommended answer and the tradeoff behind it. Wait for
   the user's reply before asking the next question.
4. Record the decision, reconsider dependent choices, and repeat while a
   consequential uncertainty remains.

For Toolbox decisions about scientific methods or workflow ownership, surface
the relevant contract and the evidence needed for the proposed change. Apply
the [verification gates](../../../docs/agent/quality/verification-gates.md) to
distinguish output parity, visible acceptance, and empirical qualification.

Finish with the agreed outcome, scope, and decisions. Include ownership,
sequencing, verification, and recovery where they affect execution. Call out
any question the user deliberately left open.
