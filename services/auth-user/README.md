# auth-user

| | |
|---|---|
| **Component** | Auth & User Service |
| **Interface owner** | Ayush |
| **Kind** | HTTP API service |
| **Owns schema** | `auth` (database role `auth_svc`) |
| **Design** | SDD 4.2.1, 7.2, 9.1; ADR-0005 |
| **Plan 2** | #91 JWT issuance and refresh rotation, plus the unticketed account endpoints |

## Responsibility

Accounts, passwords and tokens. Every other service verifies access tokens locally with `zeo_common.auth`, using
the shared `JWT_SECRET`, so no request calls this service.

| Method and path | Auth | Result |
|---|---|---|
| `POST /api/v1/auth/register` | public | `201` profile. `409 EMAIL_ALREADY_REGISTERED`, `422 VALIDATION_ERROR` (`details.field`) |
| `POST /api/v1/auth/login` | public | `200 {access_token, refresh_token, token_type, expires_in: 900, user}`. `401 INVALID_CREDENTIALS` |
| `POST /api/v1/auth/refresh` | refresh token | `200` with a **new** pair. `401 REFRESH_TOKEN_INVALID` or `REFRESH_TOKEN_REUSED` |
| `POST /api/v1/auth/logout` | refresh token | `204`. Revokes the token's whole family |
| `GET /api/v1/users/me` | bearer | Profile (never the password hash) |
| `PATCH /api/v1/users/me` | bearer | Only `display_name` can be changed |

- **Access tokens**: HS256, 15 minutes. The claims are `sub`, `role`, `kyc_status`, `suspended` and `tv` (`token_version`).
  They're re-read from the database on every refresh, so a KYC decision or suspension shows up in the next token.
- **Refresh tokens**: opaque, single-use, 14 days. Only their SHA-256 is stored. Using a token rotates it within its
  family. Presenting an already-rotated token is treated as theft: **the whole family is revoked**, which ends both
  the thief's session and the victim's (SDD 9.1).
- **Passwords**: scrypt (n=2^14, r=8, p=1) with a per-password salt. Unknown emails cost the same scrypt as
  wrong passwords, so login timing doesn't reveal which accounts exist.
- **Seeded accounts** (`infra/postgres/seed/dev-seed.sql`) have the placeholder hash `!seed`. With
  `AUTH_ACCEPT_SEED_PASSWORD=true` (Compose only) they log in with `zeo-dev-password`, which is re-hashed on first use.

## Run

```bash
docker compose up -d auth-user          # as part of the stack
cd services/auth-user && pytest         # unit tests (after installing libs/zeo-common)
```
