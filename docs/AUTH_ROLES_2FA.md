# Identity, Roles & 2FA (R5-3)

> Status: roles **implemented**; 2FA **designed, not implemented** (portfolio
> scope — external IdP integration is a deliberate non-goal; focus is on
> verifiable RBAC authorization, row-level data scoping, and access audit
> trails). This page documents the model and the 2FA design so the gap is
> explicit rather than silent.

## Role model (implemented — `backend/app/auth.py`)

| Role | Write | Read scope | Demo account |
|---|---|---|---|
| `ops` | [YES] | full network | `ops@demo.local` |
| `manager` | [YES] | full network | `manager@demo.local` |
| `partner` | [NO] | full network (read-only connected party) | `partner@demo.local` |
| `customer` | [NO] | row-level (own `customer_id` only) | `acme@demo.local` (CUST-001) |

All passwords: `demo1234`.

Enforcement helpers:
- `require_write(request)` — allows `ops`/`manager`; 403 for `partner`/`customer`.
- `require_shipment_access(request, customer_id)` — `customer` is row-scoped; the
  three full-read roles see the whole network.
- `scoped_customer_id(user)` — returns the `customer_id` a query must filter on,
  or `None` for full-read roles. Data endpoints use this for row-level isolation.
- Capability source of truth: `ROLE_CAPABILITIES` (`{write, full_read}` per role).

Every data request is audited in `fact_access_log` (principal/role/method/path/
status), so "who looked at this" is answerable (R5-3).

## 2FA — design (NOT implemented)

The demo uses an HMAC session cookie (`hkg_session`) over `email|password_hash`.
A production 2FA layer would add, without changing the role model above:

1. **Enrolment** — TOTP (RFC 6238): server generates a per-user secret, shows a
   QR (`otpauth://totp/HKG-CT:<email>?secret=...&issuer=HKG-CT`), stores the
   secret encrypted at rest (`dim_users.totp_secret_enc`), plus 10 one-time
   recovery codes (hashed).
2. **Login step-up** — after password verification, issue a short-lived
   *pre-auth* token that cannot reach data endpoints; require a valid 6-digit
   TOTP (±1 time-step drift) to exchange it for the full session cookie.
3. **Sensitive-action step-up** — write actions by `ops`/`manager` (e.g. bulk
   alert transition) may re-prompt for TOTP; this reuses the existing
   `confirmation_token` gate (R5-2) as the human-in-the-loop hook.
4. **Lockout & audit** — N failed TOTP attempts lock the account for a cool-down;
   every attempt lands in `fact_access_log` with a dedicated path marker.

### Why not implemented here
Real 2FA needs a credential store with encryption-at-rest, clock-drift handling,
recovery-code lifecycle and an enrolment UI — none of which a single-file SQLite
portfolio demo should fake. The role model and audit trail (the parts that are
verifiable and testable) are implemented; the TOTP mechanics are specified above
so the design is on record.
