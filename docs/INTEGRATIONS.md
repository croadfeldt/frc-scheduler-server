# External Integrations

This doc describes every external service the scheduler talks to, what
configuration each needs, and how to set them up. None of them are required
to run the scheduler — every integration is optional and degrades gracefully
when not configured.

## Quick reference

| Integration | Direction | Config needed | Sensitive? |
|---|---|---|---|
| **The Blue Alliance (TBA)** | We read from them | API key | yes (key) |
| **FRC Events API** | We read from them | username + token | yes (token) |
| **Statbotics** | We read from them | none | no |
| **Nexus for FRC** (webhook) | They push to us | shared secret | yes (secret) |
| **Nexus** (referral card) | UI deep-link | none | no |
| **TBA / Statbotics / FRC Events deep-links** | UI deep-link | none | no |

## Where configuration lives

All sensitive integration values are stored as Kubernetes Secrets, defined in
`openshift/01-secrets.yaml.example`. You copy that file to
`openshift/01-secrets.yaml` (which is gitignored), fill in real values, apply
it once, and then delete the unencrypted copy:

```sh
cd openshift
cp 01-secrets.yaml.example 01-secrets.yaml
# Edit values
oc apply -f 01-secrets.yaml
rm 01-secrets.yaml
```

For local development outside OpenShift, the same values are read from
environment variables. A `.env` file in the project root works (the app
reads via the `os.environ` standard mechanism).

---

## The Blue Alliance (TBA)

**What it does:** primary source of FRC event data. Match schedules,
match results, team rankings, event metadata, score breakdowns. The
scheduler uses TBA both for the editor (event picker, team list import)
and for the live view (real-time match data when an event is on TBA).

**Required for:**
- Event picker dropdown in the editor
- Team list import via "Pull from TBA" button
- The TBA-published / TBA-modified schedule source detection
- Live match data on `/view?live=1`
- The "TBA-only" fallback when an event has no local schedule

**Setup:**
1. Sign in at https://www.thebluealliance.com/account
2. Click the Read API tab
3. Click Add New Auth Key
4. Give it a description ("FRC Match Scheduler — production" works)
5. Copy the X-TBA-Auth-Key value into `TBA_API_KEY`

```yaml
# openshift/01-secrets.yaml
stringData:
  TBA_API_KEY: TBA-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**Without it:** event lookups, team imports, live data, and source detection
all fail gracefully (you can still use the scheduler manually with team lists
typed in by hand). The editor surfaces a "TBA not configured" hint when this
is missing.

**Rate limits:** TBA enforces per-key throttling. The scheduler caches all
TBA responses in memory and on disk via the `EventLiveSync` table — the live
endpoint refreshes at most once per 30 seconds per event regardless of how
many viewers are watching, so a 30-team event with 200 viewers makes the
same TBA load as one viewer.

---

## FRC Events API

**What it does:** the official FIRST API. Used as a fallback when TBA
doesn't have an event yet (some off-season events appear here first) and
for some queries that TBA doesn't expose.

**Required for:**
- Pulling event data when an event isn't on TBA
- Verifying event existence when typing in unfamiliar event keys

**Setup:**
1. Register at https://frc-events.firstinspires.org/services/API
2. You'll get a username and a token via email after approval
3. Approval is usually fast (under a day) but not instant

```yaml
# openshift/01-secrets.yaml
stringData:
  FRC_EVENTS_USERNAME: yourusername
  FRC_EVENTS_TOKEN:    a1b2c3d4-e5f6-...
```

**Without it:** the scheduler still works for any event that's on TBA. The
fallback path is silently disabled.

---

## Statbotics

**What it does:** provides Expected Points Added (EPA) ratings — basically
Elo but in match-point units, with auto/teleop/endgame splits and per-event
predicted rankings. Surfaces in the per-team panel on `/view`.

**Required for:**
- The "EPA" stat in the per-team panel on `/view`
- The "Statbotics" deep-link in per-team and per-event footers

**Setup:** none. Statbotics's read API is free and unauthenticated.

```sh
# Verify it's reachable from your cluster:
curl https://api.statbotics.io/v3/team_year/2169/2026
```

**Without it:** the EPA stat shows `—` and the deep-link still works (it's
just a URL construction). No secrets to lose.

**API used:** `GET https://api.statbotics.io/v3/team_event/{team}/{event_key}`
with a `team_year` fallback for pre-event lookups. Documented at
https://www.statbotics.io/docs/rest. The scheduler caches responses for 10
minutes per (team, event) pair to reduce load.

---

## Nexus for FRC — Webhook ingestion

**What it does:** Nexus sends real-time match queue updates ("Q14 is now
queueing", "Q15 is on deck") to our webhook endpoint. The scheduler stores
these in the `queue_status` table and surfaces them as queue pills in
`/view?live=1`.

**Required for:**
- Queueing Soon / Now Queueing / On Deck pills in the live view
- The "Nexus" data source badge showing as connected

**Setup — server side:**

1. Generate a strong random shared secret. This is what Nexus will send in
   each webhook request to prove the request is legitimate:
   ```sh
   openssl rand -hex 32
   ```

2. Store it in the secrets file:
   ```yaml
   # openshift/01-secrets.yaml
   stringData:
     NEXUS_WEBHOOK_TOKEN: 6f1c8e9d...the-output-of-openssl-rand
   ```

3. Apply secrets and restart the deployment so the env var loads:
   ```sh
   oc apply -f openshift/01-secrets.yaml
   oc rollout restart deployment/frc-scheduler-server -n frc-scheduler-server
   ```

4. Confirm the webhook endpoint is reachable from outside your cluster:
   ```sh
   curl -X POST https://frc-scheduler.example.com/api/webhooks/nexus \
     -H 'Content-Type: application/json' \
     -H 'Nexus-Token: WRONG_TOKEN_TO_TEST' \
     -d '{"type":"test"}'
   # Expect: 403 Forbidden
   ```

   If you get 403 with a wrong token, the endpoint is wired up correctly.
   The real Nexus webhook will succeed because it sends the right token.

**Setup — Nexus side:**

1. Sign in at https://frc.nexus
2. Go to your event settings (you must be an event admin on Nexus —
   typically the event organizer or a designated lead)
3. Find the Webhooks section (under Integrations or similar — Nexus's
   exact UI may have changed since this was written; look for "outgoing
   webhooks" or "webhook URL")
4. Configure:
   - **URL:** `https://frc-scheduler.example.com/api/webhooks/nexus` (your
     hostname; must be HTTPS-reachable from the public internet)
   - **Custom header:** name `Nexus-Token`, value the secret you generated
     in step 1 above (must match exactly)
   - **Events to subscribe:** match status changes (queueing, on-deck,
     on-field, completed). Schedule updates are also accepted but the
     scheduler currently ignores them — clients re-poll the schedule
     directly from TBA.
5. Send a test webhook from Nexus's UI if available

**Verifying:**

Open `/view?event=<your-event>&live=1` while the event is happening. The
live status strip should show `Nexus ●` (green). Match number cells should
get queue pills as Nexus sends webhooks: ⏳ Queueing Soon → 🟠 Now Queueing
→ 🟢 On Deck → 🟢 On Field.

If the badge stays gray (`Nexus ○`):
- Check the deployment logs: `oc logs -l app=frc-scheduler-server -n frc-scheduler-server | grep nexus`
- Verify the `NEXUS_WEBHOOK_TOKEN` env var matches what's configured in Nexus
- Confirm Nexus has actually fired any webhooks (check Nexus's webhook
  delivery log)
- Most common cause: the URL in Nexus is missing `/api/webhooks/nexus` or
  the token has whitespace

**Without it:** queue pills don't appear and the Nexus source badge stays
gray. Live match data still works via TBA.

**Security note:** the `NEXUS_WEBHOOK_TOKEN` env var is technically
optional — if unset, the webhook endpoint accepts any incoming POST. This
is fine for local development but should always be set in production.
Setting it to `""` (empty string) explicitly disables the check; setting
it to a real value enables it.

---

## Nexus for FRC — Referral card (outgoing UI link)

**What it does:** when Nexus is connected for the current event, `/view`
shows a card encouraging users to sign up for Nexus's notifications.
We don't try to compete with Nexus's notification system — theirs is
better than anything we'd build (push notifications work with the page
closed, has full delivery history, won't trigger autoplay restrictions).

**Required for:** the dismissible "Want match alerts on your phone?"
card on `/view`.

**Setup:** none. The card appears automatically when `sources.nexus.available`
is true (which requires Nexus webhooks to be configured per the section above).

**Without it:** if Nexus webhooks aren't configured, the card never shows.
Users can still find Nexus on their own.

---

## TBA / Statbotics / FRC Events — Deep-links

**What it does:** in the per-team panel and the page footer, three small
links that open the team's or event's page on each external tool.

**Required for:** the link buttons on `/view`.

**Setup:** none. These are constructed from URL patterns:
- `https://www.thebluealliance.com/team/<num>/<year>`
- `https://www.thebluealliance.com/event/<event_key>`
- `https://www.statbotics.io/team/<num>`
- `https://www.statbotics.io/event/<event_key>`
- `https://frc-events.firstinspires.org/team/<num>`
- `https://frc-events.firstinspires.org/<year>/<event_code>`

**Without it:** the links only appear when the schedule has a known event
key. If you generate a schedule for an unidentified event (typed in by
hand without TBA lookup), the deep-links section is hidden because there's
no event key to construct URLs from.

---

## Future: planned integrations

These are tracked but not yet built. The pattern is consistent: read-only
public APIs we can pull from, surfaced in `/view` as enrichment for the
team and event panels.

- **End-of-day summary URLs** — shareable static page recapping a team's
  performance at the end of qualifications. No new external integration;
  just a new view route.
- **Authenticated edits** — see `docs/AUTH_DESIGN.md` for the per-event
  manager/owner model. Will add Google OAuth requirement for editing.

We do **not** integrate with:
- **FTA Buddy** — requires direct FMS network access, against FIRST policy
- **Internal FMS data** — same reason

---

## Configuration sanity check

Quick checklist for a fresh deployment. Run each of these to verify:

```sh
# Required for any meaningful use
oc exec deploy/frc-scheduler-server -n frc-scheduler-server -- env | grep TBA_API_KEY
# Should print: TBA_API_KEY=TBA-...

# Optional but recommended for live events
oc exec deploy/frc-scheduler-server -n frc-scheduler-server -- env | grep NEXUS_WEBHOOK_TOKEN
# Should print: NEXUS_WEBHOOK_TOKEN=<your secret> (or be unset if you don't use Nexus)

# Optional fallback
oc exec deploy/frc-scheduler-server -n frc-scheduler-server -- env | grep FRC_EVENTS
# Should print FRC_EVENTS_USERNAME and FRC_EVENTS_TOKEN, or be empty
```

For Statbotics, the deep-link tools, and the Nexus referral card, no env
vars are required — they work out of the box.
