# M0.4: domain-aware destroy–repair operator credit

M0.3's unit-credit UCB found much better routes at S45, but its combined
mechanism increased total energy at S46/S47. This M0.4 modification changes
**only operator selection reward**, not routes, destroy/repair operators,
M0 CVX Stage-1/2, admission, task-success semantics, RRT acceptance, physical
residual tolerance or recorded v26/M0/M0.1/M0.2/M0.3 artifacts.

## Selection-only credit terms

The evaluator caches lightweight deterministic equal-share proxy features
on its *existing* per-candidate evaluation; there are no extra CVX calls.
The candidate is compared with the state at the time the operator was chosen:

1. **Flight cost**: UAV-specific flight-power/speed energy in *actual Joules*,
   proportional to change in route distance. A decrease of 8% of the current
   flight energy saturates this signed signal. Adding more contact visits
   provides no reward by itself.
2. **MEC-contact-associated benefit**: mean improvement in normalized
   completion time of tasks offloaded by either state, **net of incremental
   upload hover/transmission UAV energy**. This is a *proxy association*,
   not a causal marginal-MEC estimate. A contact that adds upload burden
   without reducing task completion time is penalized. Zero offloaded tasks
   means zero contact signal.
3. **Deadline pressure**: a piecewise risk score activates only when task
   completion exceeds 80% of its deadline, and saturates at 2x risk.
   Reward is tied to the reduction in mean risk across *all* tasks, not
   merely to the number of successes in an already saturated scenario.

The three signed signals are capped to [-1,1] and scaled by frozen weights
0.18, 0.14 and 0.12. They correct the M0.3 [0,1] unit UCB reward rather
than replacing the common task-success-then-lateness-then-Joules ordering.

### Guardrails

- Physically failing or lower-success candidates receive no positive
  domain credit. A better route cannot mask an extra missed deadline.
- If total normalized lateness regresses beyond the frozen tolerance,
  extra domain bonus is disallowed.
- If total candidate energy exceeds the previous current energy by
  more than 1%, no positive domain shaping is awarded. This prevents
  contact count or task-slack proxy from blindly rewarding expensive routes.
- The original M0.3 acceptance and final independent physical certificate
  are untouched. The selector's reward is not the final evaluation objective.
- Every feedback event saves base credit, adjusted credit, signed flight/
  MEC/deadline terms, upload energy and deadline pressure for interpretation.
  Unknown/missing or nonfinite features must fail, never become zeros.

## Registered frozen ablation

Five arms, identical 100 ALNS iterations and identical M0 resource recourse:
\`m03_unit_credit\` reference; \`flight_only\`; \`mec_only\`;
\`deadline_only\`; \`domain_all\`.

Registered cases: K30 S45/S48 A100, K50 S45 A100/A101, S46/S47
A100 and held-out S48/S49/S50 A100, K80 S45/S48 A100. Exactly
11 independent blocks × 5 arms = **55** search runs and **44** pair contrasts.

S45/S46/S47 were inspected for M0.3; S48/S49/S50 are a predeclared
small holdout rather than parameter-tuning scenes. K50 A101 shares the
S45 scene and is not an independent problem instance. With only three
new K50 held-out scenes, no significance or universal improvement claim.

The six earlier M0.3 UCB candidates must reproduce the archived SHA-256
fingerprints, and the solver/physics/config source fingerprints are
frozen at M0.2. Distinct M0.4 outputs live only in Actions artifacts
\`outputs/m04\`; old data and \`develop\` are never overwritten.
Equal iteration count is not equal runtime; runtime is recorded.

Run new formal 816 only *after* physical verification, negative-case
analysis and independent, equally budgeted follow-up comparisons.
