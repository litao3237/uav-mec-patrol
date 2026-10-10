"""Experimental bounded elite-candidate selectors.

The frozen ESI policy is left unchanged in problem_operators.py. These
opt-in selectors are alternatives *inside* its existing 6-candidate budget.
They never call the convex solver and make no global-optimality claims.

Ranked entries are (proxy_precheck_key, label, discrete_solution). The key
has a necessary optimistic-feasibility flag in position 0; 0 passes.
"""

CROSS_FAMILIES = frozenset({"swap", "two_opt_star", "block_relocate"})


def _legacy_subset_select(ranked, family, limit, quota):
    """Replicate legacy family-first / global-fill policy on a subset."""
    chosen = []
    seen = set()
    counts = {}
    for item in ranked:
        _, label, _ = item
        fam = family(label)
        if counts.get(fam, 0) >= quota or label in seen:
            continue
        chosen.append(item)
        seen.add(label)
        counts[fam] = counts.get(fam, 0) + 1
        if len(chosen) >= limit:
            break
    if len(chosen) < limit:
        for item in ranked:
            if item[1] in seen:
                continue
            chosen.append(item)
            seen.add(item[1])
            if len(chosen) >= limit:
                break
    return sorted(chosen, key=lambda item: item[0])


def select_protected_elite_candidates(
    ranked,
    family,
    *,
    limit: int,
    family_quota: int,
    policy: str,
):
    """Build a bounded alternative shortlist without extra CVX evaluations.

    Policies:
      replace_contact_slot: take an independent legacy shortlist *without*
        cross-route candidates, then replace only its less useful contact
        relocation / point-choice slot(s) with the best cross-route candidates.
        This protects all original route, contact-delete, and batch choices.

      protected_priority: protect one original route relocation, one contact
        deletion and one batch merge (where available), reserve one feasible
        cross-route candidate, then fill by global proxy rank. Unlike the
        legacy one-per-every-family mechanism, no other family is entitled to
        a slot. This is a hypothesis to be validated, not an established rule.

    Candidates failing the optimistic necessary precheck are not allowed to
    displace a candidate when selecting a cross-route representative.
    """
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be positive")
    if not isinstance(family_quota, int) or family_quota <= 0:
        raise ValueError("family_quota must be positive")
    if policy not in {"replace_contact_slot", "protected_priority"}:
        raise ValueError("Unsupported selection policy")
    ranked = sorted(ranked, key=lambda item: item[0])
    seen = set()
    chosen = []
    trace = {"selection_policy": policy, "replaced": [], "protected": []}

    def add(item, *, category=None):
        if item is None or item[1] in seen or len(chosen) >= limit:
            return False
        chosen.append(item)
        seen.add(item[1])
        if category is not None:
            trace["protected"].append({"family": category, "label": item[1]})
        return True

    def best(items, *, precheck_only=False):
        return next(
            (item for item in items
             if item[1] not in seen
             and (not precheck_only or float(item[0][0]) == 0.0)),
            None,
        )

    originals = [item for item in ranked if family(item[1]) not in CROSS_FAMILIES]
    cross = [
        item for item in ranked
        if family(item[1]) in CROSS_FAMILIES and float(item[0][0]) == 0.0
    ]
    if policy == "replace_contact_slot":
        baseline = _legacy_subset_select(originals, family, limit, family_quota)
        trace["original_baseline_labels"] = [item[1] for item in baseline]
        for item in baseline:
            if family(item[1]) == "contact":
                repl = best(cross)
                if repl is not None:
                    if add(repl):
                        trace["replaced"].append({
                            "old": item[1],
                            "new": repl[1],
                        })
                        continue
            add(item)
        # If the legacy shortlist was not full, backfill with new candidates.
        if len(chosen) < limit:
            for item in cross:
                add(item)
        return sorted(chosen, key=lambda item: item[0]), trace

    for protected_family in ("route", "contact_remove", "batch_merge"):
        item = best(
            (x for x in originals if family(x[1]) == protected_family),
            precheck_only=True,
        )
        add(item, category=protected_family)
    add(best(cross), category="cross_route")
    # Fill from remaining valid candidates globally, without forcing
    # unproductive families to receive a mandatory CVX slot.
    for item in ranked:
        if float(item[0][0]) == 0.0:
            add(item)
    # If none or too few candidates pass the necessary check, return fewer
    # candidates rather than spend Stage-1 validation calls on certified
    # impossible states. This is a deterministic true-precheck filter.
    return sorted(chosen, key=lambda item: item[0]), trace
