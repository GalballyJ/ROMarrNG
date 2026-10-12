---
category: fixed
audience: users, operators
area: library
action: none
breaking: false
---
ROMarr refreshes password-grant RomM tokens before expiry and safely retries RomM 5.3.1's expired-token error, keeping library reads available without treating a real server outage as an authentication failure.
