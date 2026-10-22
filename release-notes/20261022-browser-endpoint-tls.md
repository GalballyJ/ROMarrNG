---
category: security
audience: operators
area: downloader
action: Configure a trusted certificate for remote browser endpoints
breaking: false
---

Remote browser downloader endpoints now use TLS by default and reject URL credentials. Configure a certificate trusted by the browser, or explicitly set `ROMARR_ALLOW_INSECURE_BROWSER_ENDPOINTS=true` only on an isolated trusted network that cannot use TLS.
