# Auth & Authorization Design

This doc tracks the design for a future landing that adds enforced authentication
and per-event authorization. Not yet implemented.

## Current state

- `get_current_user` and `require_auth` exist in `app/auth.py`
- A handful of endpoints already pass `current_user: dict | None = Depends(get_current_user)`
  but **don't enforce** anything — they just record `created_by`
- The frontend has a Google OAuth login flow that's optional
- All `/api/...` endpoints are publicly readable; all mutations are publicly writable
- The `/view` page is intentionally public — anyone with the URL can see a schedule

## Goals

1. **Public read** for `/view` and `/api/events/by-key/...` should stay public.
   Teams, audiences, and printed flyers need this to work without login.
2. **Authenticated edit** — creating, updating, or deleting schedules requires
   a logged-in user.
3. **Per-event ownership** — each Event has one or more "managers" who can
   modify schedules for that event. Other users can read but not write.
4. **Admin escalation** — a small set of users have global write access for
   moderation, debugging, and recovery.

## Proposed model

### New tables

```python
class EventManager(Base):
    """Grants a user write access to a specific event."""
    __tablename__ = "event_managers"
    event_id:   Mapped[int]  = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    user_sub:   Mapped[str]  = mapped_column(String(256), primary_key=True)  # OAuth subject
    role:       Mapped[str]  = mapped_column(String(32), default="manager")  # 'manager' | 'owner'
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    granted_by: Mapped[str|None] = mapped_column(String(256), nullable=True)
```

### User flags (extend existing User table)

```python
class User(Base):
    # ... existing fields ...
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
```

### Auth dependency helpers

```python
async def require_event_write(event_id: int, current_user: dict, db: AsyncSession):
    """Raise 403 unless current_user is an admin or has manager/owner role
    on the given event. Returns the role on success."""
    if not current_user:
        raise HTTPException(401, "Authentication required")
    user_sub = current_user["sub"]
    # Admin shortcut
    user_row = await db.get(User, user_sub)
    if user_row and user_row.is_admin:
        return "admin"
    # Per-event check
    res = await db.execute(
        select(EventManager).where(
            EventManager.event_id == event_id,
            EventManager.user_sub == user_sub,
        )
    )
    em = res.scalar_one_or_none()
    if not em:
        raise HTTPException(403, "Not authorized to modify this event")
    return em.role
```

## Endpoint enforcement

| Endpoint | Today | Future |
|----------|-------|--------|
| `GET /api/events`                              | public | public |
| `GET /api/events/{id}`                         | public | public |
| `GET /api/events/by-key/{key}/view-payload`    | public | public |
| `GET /api/events/{id}/live`                    | public | public |
| `GET /api/assigned-schedules/{id}`             | public | public |
| `POST /api/events`                             | public | login required |
| `PATCH /api/events/{id}/branding`              | public | event-write required |
| `DELETE /api/events/{id}`                      | public | event-write (owner only) |
| `POST /api/abstract-schedules/.../assign`      | public | event-write required |
| `POST /api/assigned-schedules/{id}/activate`   | public | event-write required |
| `DELETE /api/assigned-schedules/{id}`          | public | event-write required |
| `POST /api/assigned-schedules/{id}/duplicate`  | public | login required |
| `POST /api/events/{id}/simulate/start`         | public | event-write required |
| `POST /api/events/{id}/simulate/stop`          | public | event-write required |
| `POST /api/webhooks/nexus`                     | header-token | header-token (unchanged) |

## Bootstrap flow

1. Anonymous user visits `/?event=2026mnst` (editor)
2. Editor detects no auth, shows "Sign in to edit" overlay over Configuration panel
3. User signs in with Google
4. If user has no EventManager rows, editor shows "You don't have edit access
   to any events. Contact an admin to be added as a manager."
5. Admin (via a `/admin` page or CLI) can grant a user manager access to specific events
6. First admin is bootstrapped via env var `ADMIN_EMAILS=foo@bar.com,...` or
   manually via `oc rsh ... python3 -c "..."` SQL

## Migration

- Adding `event_managers` table is additive; doesn't break anything
- Adding `users.is_admin` column is additive
- Adding enforcement to endpoints would break existing usage — needs a flag
  `AUTH_ENFORCEMENT_MODE` with values:
    - `off` (default, current behavior — no enforcement)
    - `warn` (logs would-be 403s but allows the request through)
    - `on` (full enforcement)
- Run for ~1 week in `warn` mode to surface anyone whose flow would break,
  then flip to `on`

## Open questions

1. **Anonymous read of /view for unpublished local-only schedules** — do we
   want anyone to see a draft schedule by guessing event keys? Probably yes
   for now; add a `events.public` flag if it becomes a concern.
2. **Sharing between accounts** — when a manager wants a teammate to also
   manage, who can grant? Owner-only? Any manager? Initial: owner-only.
3. **Audit log** — track who granted what, who modified schedules. New
   `audit_log` table with (timestamp, user, action, target). Useful but adds
   work; defer until requested.
4. **API tokens for external automation** — Nexus already has a header token.
   For tools that want to call our API on behalf of an event, support a per-event
   token model. Defer.
