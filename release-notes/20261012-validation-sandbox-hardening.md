---
category: security
audience: operators
area: ci-security
action: none
breaking: false
---

Validation snapshots exclude dotted and extensionless credentials, private/API keys, access/refresh-token and client-secret material, suffixed dotenv credentials, and non-source files under credential folders. Source modules and safe templates such as tokens.env.example remain available to tests.
