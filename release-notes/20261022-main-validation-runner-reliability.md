---
category: fixed
audience: operators
area: validation
action: none
breaking: false
---
Trusted main validation now carries only the verified Python tool-cache library path into its test processes, and the packaged acquisition checks receive Docker in their disposable runner VMs. Pull-request validation remains isolated from the shared main runner pool.
