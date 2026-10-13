---
category: security
audience: operators
area: validation
action: none
breaking: false
---
ROMarrNG's packaged acquisition proof now rejects TLS 1.0 and 1.1 on its local HTTPS fixture, requiring TLS 1.2 or newer. This improves security validation without changing the application's runtime network behavior.
