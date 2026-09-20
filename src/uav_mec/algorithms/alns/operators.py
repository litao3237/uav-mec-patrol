"""Problem-specific ALNS operators will live here.

Planned operator families:
- task relocate / swap / 2-opt
- contact insert / remove / replace / point-shift
- batch split / merge / reassign
- local <-> offload mode switch
- deadline-critical and shadow-price-assisted repair

Version 0.2 deliberately does not implement these yet. The resource model is
validated first, then operators are added one family at a time with unit tests.
"""
