---
category: security
audience: operators
area: metadata
action: none
breaking: false
---
IGDB client credentials now travel in the HTTPS token request body rather than its URL, keeping the client secret out of query strings recorded by proxies and request logs.
