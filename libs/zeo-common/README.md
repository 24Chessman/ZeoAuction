# zeo-common — the service template

**Owner:** Ayush (Infrastructure). Changes need a review from Ayush plus one other member.

This is the shared library every ZeoAuction service is created from. A new service gets the platform conventions
from one call:

```python
from zeo_common import create_app

app = create_app("bid", version="0.1.0")
```

| Provided | Where it comes from |
|---|---|
| `GET /healthz` (liveness; used by Compose and Render health checks) | `health.py` |
| `GET /readyz` (503 until every registered check passes) | `health.py`, via `app.state.readiness.add_check(name, async_fn)` |
| `GET /metrics` (Prometheus; per-app registry at `app.state.metrics`) | `metrics.py` |
| `X-Request-ID` propagation (UUID) | `request_context.py` |
| Uniform error envelope `{code, message, details, request_id}` | `errors.py`, via `raise ApiError(code, message, status)` |
| JSON logs with `service` and `request_id` | `logging_setup.py` |
| Money as two-decimal strings, never floats | `money.py`: `parse_money` / `format_money` |
| API docs at `/api/v1/docs`, spec at `/api/v1/openapi.json` | `app_factory.py` |
| Bearer-token verification (`CurrentPrincipal`, `AdminPrincipal`) | `auth.py`, after `install_auth(app)` |
| Gateway gates: `VerifiedSeller` (listing gate, CT-2), `ActivePrincipal`, `require_roles(...)`, and the forced-refresh check `FreshPrincipal` against `tv:{user_id}` | `gateway.py`, after `install_gateway(app, RedisTokenVersions(redis))` |
| S3-compatible object storage: SigV4-signed uploads with SSE-S3, signed GET URLs capped at 300 s, keys never URLs | `storage.py`: `S3ObjectStore(StorageSettings.from_env("kyc-documents"))` |
| Bearer-token verification (`CurrentPrincipal`, `AdminPrincipal`) | `auth.py`, after `install_auth(app)` |
| Gateway gates: `VerifiedSeller` (listing gate, CT-2), `ActivePrincipal`, `require_roles(...)`, and the forced-refresh check `FreshPrincipal` against `tv:{user_id}` | `gateway.py`, after `install_gateway(app, RedisTokenVersions(redis))` |
| S3-compatible object storage: SigV4-signed uploads with SSE-S3, signed GET URLs capped at 300 s, keys never URLs | `storage.py`: `S3ObjectStore(StorageSettings.from_env("kyc-documents"))` |

Run the tests:

```bash
pip install ./libs/zeo-common -r requirements-dev.txt
pytest libs/zeo-common
```
