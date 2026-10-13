---
category: changed
audience: operators
area: validation
action: none
breaking: false
---
ROMarrNG now runs its independent offline test files in a bounded two-task pool, reducing CI wait time while preserving pytest's configured exclusions, per-task counts, and the source receipt checked before image builds.
