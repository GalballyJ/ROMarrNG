---
category: fixed
audience: operators
area: containers
action: none
breaking: false
---
ROMarrNG release images now keep `:main` and `:latest` on the same stable release. Main-branch CI uses commit-specific tags, and validated standard and browser images are mirrored to Docker Hub when publisher credentials are configured. Unraid templates follow the stable `:latest` aliases.
