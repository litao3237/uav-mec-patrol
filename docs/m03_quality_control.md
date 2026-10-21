# M0.3: Physically interpretable ALNS acceptance and bounded operator credit

M0.2 identified why merely changing the score normalization can change RRT
acceptance: the stock algorithm computes the initial threshold as a fraction
of the *scalar* objective, which includes the task-count constant and bounded
energy term. The first different acceptance at K50/S45/A100 appeared at
iteration 23, before changed candidate structures (iteration 24) and
operator selection (iteration 31).

## Two opt-in mechanisms

### 1. TaskQoSRecordToRecord

The new acceptance criterion reads the **same screened evaluator's cached
physical/task-quality tuple**. No extra resource solver call is needed.

1. Physically unqualified candidates are rejected; existing hard
   radio, route, MEC bandwidth/CPU, battery and return constraints are
   unchanged.
2. Losing one or more on-time tasks compared with the incumbent best is
   rejected during the candidate acceptance criterion.
3. Gaining on-time tasks or reducing normalized lateness beyond numerical
   tolerance is accepted without asking a bounded scalar to justify it.
4. If success count is unchanged and lateness is within a predeclared window,
   candidates may temporarily increase true energy in **Joules** up to
   8% of best energy at the beginning, cooling to 0% after 100 decisions.
   The lateness window simultaneously cools from .01 to 0.

These are *exploration* allowances, not the final solution acceptance,
strict success-count optimality, or permission to violate physical
constraints. The ALNS built-in global-best object still ranks the candidate
using the M0 scalar surrogate; the final saved scheme is subsequently
independently measured.

### 2. UnitCreditBandit

Selection is a coupled-pair UCB. Each admissible destroy/repair pair starts
with one exploratory draw. Subsequent selection uses the mean of bounded
[0,1] rewards and an explicit uncertainty bonus (exploration .28):

- 1.00 for increased on-time tasks;
- 0.85 for reduced lateness in the same success tier;
- 0.55–0.80 for actual Joule energy improvement with unchanged QoS;
- 0.40 for improving the previous current solution;
- 0.10 for accepted exploratory candidates;
- 0 for physical failures/rejections.

A novel, physically qualified candidate may receive up to 0.05 extra
credit, capped at 1.00. This is not a neural bandit: it requires no
offline training and cannot infer global optimality. The score is
independent of the ALNS composite scalar's units.

## Four-arm controlled factorial

| Arm | Acceptance | Operator selection |
| --- | --- | --- |
| baseline | M0 scalar RRT | existing adaptive roulette |
| unit_acceptance | task-QoS/real-Joule RRT | existing adaptive roulette |
| unit_credit | M0 scalar RRT | bounded UCB credit |
| combined | task-QoS/real-Joule RRT | bounded UCB credit |

Run K30, K50, K80 at S45 seed100 plus K50 S46/S47 seed100 and K50
S45 seed101. Exactly six registered case blocks, 24 ALNS searches
(100 iterations), and 18 contrasts with the baseline, all with the
same M0 resource recourse and independent physical verification.

The baseline K30/50/80 S45/A100 candidate SHA-256 must match the
archived M0.2 fingerprints. The CVX solver, physics and YAML input
SHA-256 identities are frozen. The full old recorded evidence under
\`results/\` is hash-verified, not rewritten. This diagnostic does NOT
imply equal wall-clock budgets or statistical proof across independent
scenarios. No 816-run matrix is started.

## Acceptance criteria for later research

Do not declare M0.3 a performance win from one scene, or simply because
new operators take additional CPU time. Report task success first,
lateness second, then energy/distance, runtime, and non-improved cases.
If the acceptance-only and combined arms fail to improve robustly,
calibrate or redesign within isolated evidence before adding genetic
crossovers, VND, path relinking or new hardware constraints.
