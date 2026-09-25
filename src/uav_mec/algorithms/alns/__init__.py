# 两条 v5 分支使用不同预算规则；检查点版本采用明确别名，防止配置被同名导入覆盖。
from .budget_aware_terminal_first import (
    BudgetAwareTerminalFirstConfig as CheckpointBudgetAwareTerminalFirstConfig,
    BudgetAwareTerminalFirstResult as CheckpointBudgetAwareTerminalFirstResult,
    run_uav_mec_budget_aware_terminal_first_esi_alns,
)
from .energy_guided import (
    EnergyGuidedESIConfig,
    energy_guided_intensification,
    make_energy_guided_intensifier,
)
from .budget_aware import (
    BudgetAwareTerminalFirstConfig,
    BudgetAwareTerminalFirstResult,
    run_uav_mec_budget_aware_terminal_first_alns,
)
from .terminal_first import (
    TerminalFirstESIConfig,
    TerminalFirstESIResult,
    run_uav_mec_terminal_first_esi_alns,
)
from .terminal_recovery import (
    TerminalRecoveryESIConfig,
    TerminalRecoveryESIResult,
    run_uav_mec_terminal_recovery_esi_alns,
)
from .continuous import (
    ContinuousESIConfig,
    ContinuousESIResult,
    run_uav_mec_continuous_esi_alns,
)
from .adaptive import (
    AdaptiveESIConfig,
    AdaptiveESIResult,
    run_uav_mec_adaptive_esi_alns,
)
from .evaluator import (
    KKTObjectiveEvaluator,
    ProxyObjectiveEvaluator,
    ScreenedProxyObjectiveEvaluator,
    solution_signature,
)
from .hybrid import (
    HybridUavMecALNSResult,
    Stage1CVXObjectiveOracle,
    run_uav_mec_hybrid_alns,
)
from .operators import (
    DestroyConfig,
    cheapest_insertion_repair,
    critical_task_removal,
    make_destroy_operators,
    make_repair_operators,
    random_task_removal,
    regret2_insertion_repair,
    route_segment_removal,
)
from .problem_operators import (
    ProblemOperatorConfig,
    compute_aware_insertion_repair,
    contact_opportunity_repair,
    mec_batch_pressure_removal,
    mode_batch_repair,
    shared_mec_pressure_removal,
)
from .runner import (
    UavMecALNSConfig,
    UavMecALNSResult,
    run_uav_mec_alns,
)
from .session import (
    UavMecALNSCheckpoint,
    UavMecALNSSegmentResult,
    UavMecALNSSession,
)
from .state import UavMecState

__all__ = [
    "CheckpointBudgetAwareTerminalFirstConfig",
    "CheckpointBudgetAwareTerminalFirstResult",
    "run_uav_mec_budget_aware_terminal_first_esi_alns",
    "AdaptiveESIConfig",
    "BudgetAwareTerminalFirstConfig",
    "BudgetAwareTerminalFirstResult",
    "AdaptiveESIResult",
    "ContinuousESIConfig",
    "ContinuousESIResult",
    "TerminalFirstESIConfig",
    "TerminalFirstESIResult",
    "TerminalRecoveryESIConfig",
    "TerminalRecoveryESIResult",
    "DestroyConfig",
    "EnergyGuidedESIConfig",
    "HybridUavMecALNSResult",
    "KKTObjectiveEvaluator",
    "ProxyObjectiveEvaluator",
    "ProblemOperatorConfig",
    "ScreenedProxyObjectiveEvaluator",
    "Stage1CVXObjectiveOracle",
    "UavMecALNSCheckpoint",
    "UavMecALNSConfig",
    "UavMecALNSResult",
    "UavMecALNSSegmentResult",
    "UavMecALNSSession",
    "UavMecState",
    "cheapest_insertion_repair",
    "compute_aware_insertion_repair",
    "contact_opportunity_repair",
    "critical_task_removal",
    "make_destroy_operators",
    "make_repair_operators",
    "mec_batch_pressure_removal",
    "mode_batch_repair",
    "random_task_removal",
    "regret2_insertion_repair",
    "route_segment_removal",
    "shared_mec_pressure_removal",
    "run_uav_mec_adaptive_esi_alns",
    "run_uav_mec_budget_aware_terminal_first_alns",
    "run_uav_mec_continuous_esi_alns",
    "run_uav_mec_terminal_first_esi_alns",
    "run_uav_mec_terminal_recovery_esi_alns",
    "run_uav_mec_alns",
    "run_uav_mec_hybrid_alns",
    "energy_guided_intensification",
    "make_energy_guided_intensifier",
    "solution_signature",
]
