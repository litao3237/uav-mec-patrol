# E1: opt-in Zeng rotary UAV energy model

- **Legacy default:** `configs/baseline.yaml` keeps flight 180 W and hover 200 W, unchanged. Archived instance fingerprints are preserved (new constant-mode UAV fields are omitted from the JSON snapshot).
- **Rotor scenario:** `configs/rotor_e1.yaml` selects `propulsion_model: rotor`, with P0=79.86 W, Pi=88.63 W, tip speed=120 m/s, induced speed=4.03 m/s, drag ratio=.6, air density=1.225 kg/m³, solidity=.05, rotor disk=.503 m². These are **one literature-used parameter set**, not the aircraft measured in Zeng's original experiment.
- **Formula:** Y. Zeng, J. Xu and R. Zhang, *Energy Minimization for Wireless Communication With Rotary-Wing UAV*, IEEE Transactions on Wireless Communications 18(4), 2019, DOI:10.1109/TWC.2019.2902559. The horizontal constant-speed rotary model includes profile, induced and parasitic drag terms; hover evaluates the same function at v=0.
- **Assumptions:** steady level flight at 10 m/s; no acceleration, turning, climb, descent or payload-dependent transients. Hovering during task collection and MEC contact upload still holds. The existing route timing, upload CPU allocations, QoS and battery constraints remain intact.
- **Energy components:** flight = P(10) × distance/10; task collection hover = P(0) × task collection duration; MEC upload hover = P(0) × upload duration; RF tx remains 0.1 W × upload duration; local DVFS remains κWf². Ground MEC electricity is **not** part of UAV energy/battery.
- **Physical reliability:** optimized conic energy objective, event lower bounds, the exact reconstructed timing and independent saved/rebuilt physical battery auditors must use the same selected propulsion model.
- **Experiment discipline:** compute a fixed-matched scenario comparing the original baseline to rotor E1; never splice original energy components into rotor outcomes and never alter old results. Do not interpret a lower rotor-based Joule value as the new algorithm outperforming the old algorithm under identical physical settings. Search for all 7 methods only after E1 baseline checks pass.

## Quick checks

```bash
pytest -q tests/test_e1_rotor_physics.py tests/test_task_qos.py tests/test_resource_solver.py
python experiments/run_seven_methods.py --tasks 30 --scenario 45 --phase pilot --qos-mode task-level --config configs/rotor_e1.yaml --output outputs/e1/K30_S45.json
```
