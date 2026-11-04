"""Repository-wide CK / ckjm-style OO metrics for Python classes.

Conventions follow ckjm (the tool behind the PROMISE CK datasets) so values are on the
training data's scale:
  WMC   = number of methods (unit weights)            NPM = public methods
  DIT   = 1 for a root class; +1 per resolved ancestor (unknown external base counts as 1)
  NOC   = direct subclasses within the repository
  Ce    = distinct types this class uses              Ca  = repo classes that use it
  CBO   = |Ce ∪ Ca|
  RFC   = |own methods ∪ distinct methods called|
  LCOM  = CK'94: max(P − Q, 0) over method pairs sharing / not sharing instance fields
  LCOM3 = Henderson-Sellers; ckjm returns 2 when m ≤ 1 or no fields
  LOC   = Σ method bytecode instructions (ckjm counts bytecode, not source lines)
  AMC   = LOC / WMC         max_cc / avg_cc = McCabe over methods
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from app.metrics.python_metrics import ClassFacts
from app.ml.features import CLASS_FEATURES


def compute_oo_metrics(classes: list[ClassFacts]) -> dict[tuple[str, str], dict[str, float]]:
    """Return {(file, qualname): metrics} with every CLASS_FEATURES key."""
    by_name: dict[str, list[ClassFacts]] = defaultdict(list)
    for c in classes:
        by_name[c.name].append(c)

    children: dict[str, int] = defaultdict(int)
    for c in classes:
        for b in set(c.bases):
            if b in by_name:
                children[b] += 1

    users: dict[str, set[str]] = defaultdict(set)  # class name -> names of classes using it
    for c in classes:
        for ref in c.referenced:
            if ref in by_name and ref != c.name:
                users[ref].add(c.qualname)

    depth_cache: dict[str, int] = {}

    def dit(name: str, seen: frozenset = frozenset()) -> int:
        if name in depth_cache:
            return depth_cache[name]
        if name in seen:  # inheritance cycle (or name clash) — stop
            return 1
        cand = by_name.get(name)
        if not cand:
            return 1  # external class: treat as a root
        bases = cand[0].bases
        d = 1 if not bases else 1 + max(dit(b, seen | {name}) for b in bases)
        depth_cache[name] = d
        return d

    out: dict[tuple[str, str], dict[str, float]] = {}
    for c in classes:
        m = len(c.methods)
        ccs = [x.cc for x in c.methods]
        calls = set().union(*(x.calls for x in c.methods)) if c.methods else set()
        loc = sum(x.bytecode for x in c.methods)

        fields_per_method = [x.fields for x in c.methods]
        p = q = 0
        for a, b in combinations(fields_per_method, 2):
            if a & b:
                q += 1
            else:
                p += 1
        lcom = max(p - q, 0)

        attrs = set().union(*fields_per_method) | c.class_attrs if c.methods else c.class_attrs
        if m <= 1 or not attrs:
            lcom3 = 2.0
        else:
            mu_sum = sum(sum(1 for f in fields_per_method if a in f) for a in attrs)
            lcom3 = (m - mu_sum / len(attrs)) / (m - 1)
            lcom3 = min(2.0, max(0.0, lcom3))

        ce_set = set(c.referenced)
        ca_set = users.get(c.name, set())
        metrics = {
            "wmc": float(m),
            "dit": float(dit(c.name)),
            "noc": float(children.get(c.name, 0)),
            "cbo": float(len(ce_set | {u.rsplit(".", 1)[-1] for u in ca_set})),
            "rfc": float(len({x.name for x in c.methods} | calls)),
            "lcom": float(lcom),
            "loc": float(loc),
            "max_cc": float(max(ccs, default=0)),
            "avg_cc": float(sum(ccs) / m) if m else 0.0,
            "ce": float(len(ce_set)),
            "npm": float(sum(1 for x in c.methods if x.is_public)),
            "amc": float(loc / m) if m else 0.0,
            "lcom3": round(lcom3, 4),
        }
        out[(c.file, c.qualname)] = {k: metrics[k] for k in CLASS_FEATURES}
    return out
