---
category: security
audience: operators
area: validation
action: none
breaking: false
---

Dependency installation is limited to hosted CI and receives only explicitly approved proxy, private-index, and custom CA settings; local offline tests use a preconfigured Python environment. Hosted checkouts no longer persist their token into `.git/config`, and Linux task children cannot read the validation runner's environment through procfs.
