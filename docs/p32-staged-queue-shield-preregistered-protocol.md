# P32 — Frozen staged necessary-condition guard; first-use S139–S142

**Protocol locked before inspecting any S139–S142 numerical outcome.**
Date: 2026-10-14. Branch `experiment/p32-staged-queue-shield-firstuse`.
This is a NEW exploration after P31, not a retuning/reclassification of
P31's S135–S138 independent results. The official `develop`,
paper results, original MEC CPU/BW hardware, Task/Route physics,
original ALNS's builder, destroy/roulette/RRT and full Stage1/Stage2
residual audit are unchanged.

## Motivation from previous (development) findings

P29/P30 independently proved a positive posthoc structural S91 case:
migrate E1's deadline-binding S36 from U2 to U1 and offload via an
existing E2 contact, retaining original physical capacity. P31's actual
ALNS first-use on S135–S138 did NOT meet its preregistered success gate.
P31 original 29/36, queue_only 30/36 (one new, no loss), joint_cpu_bw
29/36 (one new, one lost), sham 28/36. The joint screen was expensive.
These used data are **not new test observations in P32**.

P32 frozen hypothesis: protect any repaired D that already passes both
safe optimistic FIFO/EDF queue and static station CPU necessary tests.
Only consider cross-UAV repair when either fails. This can reduce harm
from gratuitous discrete changes and reduce original-ALNS operator cost;
it does **not** guarantee preserving the outcome of a separate
original ALNS run under time-scaled stochastic search.

## Frozen arms and exact algorithm change

For each original cheapest/regret2 repair, first invoke exactly one
unchanged original full-MEC greedy builder. The P32 hook then:

1. Compute original queue-aware optimistic timing necessary test and
   original static station CPU-share necessary test.
2. If both pass, return original repaired D unchanged, without an
   additional DP joint-bandwidth/CPU diagnostic.
3. Otherwise identify **up to two** original P31 binding-pair tasks
   from existing static resource lower bounds, generate the exact same
   **up to 24** legal cross-UAV moves as P31, using up to three
   alternate UAVs, original two best+earliest insertion positions,
   local execution or up to two original downstream alternate-MEC
   contacts. No new MEC contact and no more greedy builders.
4. For each candidate, compute queue/CPU necessary tests. **Only**
   candidate D passing BOTH can be selected for the ALNS repair.
5. `queue_guard`: select eligible candidate minimizing normalized
   optimistic deadline/delay/cycle excess and route length.
   `cpu_guard`: select eligible candidate minimizing static CPU
   pressure, then excess and timing.
   `joint_gate`: form a deterministic union of up to four
   queue-ranked and four CPU-ranked cheap-eligible candidates;
   evaluate original 16-bin optimistic joint bandwidth-CPU
   necessary bound; select only a joint-necessary-passing candidate.
   `sham_joint`: perform the IDENTICAL diagnostics/selection as
   `joint_gate` but always return original repaired D.
6. Never call the original Stage1 or Stage2 solver inside the cheap
   candidate loop. Later ALNS exploration, objective and acceptance,
   elite stage and final strict verification remain original.

Six preregistered arms, in this order:
`original`, `p31_queue_only` (unaltered P31 first-use reference),
`sham_joint`, `queue_guard`, `cpu_guard`, `joint_gate`.

**Screening workload is deliberately *not* equal across all arms.**
The sham matches the joint branch's diagnostic work, whereas queue
and CPU arms skip joint conic-independent DP screens. Every arm shares
the same scene and initial D, nested algorithm seed and nominal clock;
real runtime, iterations, generated moves, extra screens and complete
wall time must be reported. Queue/CPU necessary passing is **not**
equivalent to a strict feasible solution; a full strict Stage1 +
independent Stage2 result is the ONLY accepted feasibility metric.
No claim of exact equal iterations, hard 8 s wall time, or deterministic
wall-clock comparisons across OS.

## Preregistered independent first-use sample

Scenes **S139, S140, S141, S142** have never been used in P0–P31
mechanism design. For each scene, run task scales `K30,K50,K80`
with 5 UAVs and 2 active MEC stations and three physically
nested profiles `baseline,compute_x1p5,deadline_x0p9`.
Use the original and same nested algorithm seed **191**.
There are 4 independent spatial layouts × 3 task scales × 3 profiles =
**36 paired physical/seed rows** × 6 arms = **216 full ALNS runs**.
Independent spatial sample count is **four**, not 36 or 216.

B exploration nominal **6 seconds**, ESI elite nominal **2 seconds**,
original time-scaled RRT, original elite oracle and Stage1/Stage2
recomputation each arm. 6+2 is NOT a hard end-to-end runtime cap.
Archive every failed solver/classification and preserve source/model
SHA identities, even when no successful candidate exists.

## Primary endpoint, preregistered thresholds and negative results

Primary new algorithm arm is `queue_guard`, chosen **before any new
holdout outcome is observed**. Stage1+Stage2 strict ESI qualification
versus `original` in the same full scene/K/profile/seed case, including
new gains and lost original success.

Exploratory threshold requires ALL:
- Gains on at least **two different new spatial layouts**.
- Gains on at least **two different K task scales**.
- **Zero** original strict-success losses.

Secondary outcomes: `joint_gate` vs `queue_guard` and `sham_joint`,
the old `p31_queue_only` reference, differences in the number of B
iterations, CPU BW diagnostic calls, total wall time and energy
**only on pairs where both arms strictly qualify**.

If the primary gate fails, freeze/report the negative result unchanged
and design another scientifically distinct preregistered experiment on
S143+; never optimize on the S139–S142 results and pass them off as
unseen. Even if thresholds pass, four independent spatial scenes and
one nested algorithm seed do not yield statistical proof of broad
superiority.

All code, tests, documentation and workflows remain in an isolated
`experiment/` branch; no merge into official `develop`.
