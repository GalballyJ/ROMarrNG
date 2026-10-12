---
category: security
audience: operators
area: plugins
action: none
breaking: false
---

ROM Hub plugins now have bounded temporary storage and cannot change file permissions, spawn child processes, or use io_uring to bypass socket restrictions. The trusted SDK runner loads before plugin paths become importable. Plugin file access stays within installed code, approved assets, and required runtime files, reducing the impact of a misbehaving source.
