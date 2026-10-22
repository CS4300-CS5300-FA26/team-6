# Canvas token storage

Status: Accepted for issue 38, 2026-10-19.

## Context

Canvas+ must reuse a student's personal access token after their browser session
ends, while displaying only its last four characters. The application must recover
the original token to authenticate to Canvas, so a password hash cannot meet this need.

## Decision

Store one CanvasConnection per Django user. Encrypt the complete token using
cryptography's authenticated Fernet implementation and a dedicated environment key,
independent of Django's SECRET_KEY. Store the display suffix separately. Bind the
credential to the Canvas origin on which it was validated and scope every query to
the authenticated user. Save credentials only after a successful course request.

## Consequences

Database contents alone do not reveal the full token, but access to both the database
and the environment key permits decryption. Operators must keep the key stable and
back it up securely. Missing or malformed keys prevent saving connections; unreadable
saved ciphertext requires reconnection. Key rotation with migration of existing
ciphertext is future work. No plaintext token is placed in browser storage or session
data, and the connection page disables caching. Only an explicit Canvas authentication
rejection expires a credential during normal API operation; outages preserve it.
