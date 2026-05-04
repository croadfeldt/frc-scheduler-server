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
| **LLM endpoint** (PDF import) | We send PDFs to it | endpoint URL + model name | yes if remote |

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

## LLM endpoint (PDF schedule import)

**What it does:** parses arbitrary qualification schedule PDFs into the
scheduler's match format, so events can be imported from sources that
aren't TBA-tracked. The PDF text is extracted server-side via pdfplumber,
then sent to an OpenAI-compatible LLM endpoint for parsing into structured
JSON. The user reviews the parsed result (with editable cells) and confirms
before import.

**Required for:**
- The "Import schedule from PDF…" button in the editor
- Importing schedules from MSHSL state, off-season events, or any source
  that publishes a PDF schedule but isn't in TBA

**Setup — endpoint side:**

You need any OpenAI-compatible endpoint. Two common self-hosted options:

- **vLLM** — `vllm serve <model>` exposes `/v1/chat/completions` natively
- **llama.cpp** — `llama-server --model <path>.gguf` with `--port 8000`

Both serve OpenAI-compatible HTTP. We've tested with **Qwen3-32B Q8** running
on llama.cpp; the LLM client passes llama.cpp-specific knobs
(`top_k`, `min_p`, `cache_prompt`, `chat_template_kwargs`) at the top level
of the request body, which other servers will ignore harmlessly.

**Setup — scheduler side:**

```yaml
# openshift/01-secrets.yaml
stringData:
  LLM_ENDPOINT:  "http://your-llm-host:8000/v1"
  LLM_MODEL:     "qwen"        # whatever name your server expects
  LLM_API_KEY:   ""            # most self-hosted endpoints don't auth
```

Apply secrets and restart:

```sh
oc apply -f openshift/01-secrets.yaml
oc rollout restart deployment/frc-scheduler-server -n frc-scheduler-server
```

**Verifying:**

1. Open the editor and load any event
2. Look for the "Import schedule from PDF…" button below "Generate Schedule"
3. The status badge next to it shows green when the LLM is reachable

If the button stays hidden:
- Check the deployment env: `oc exec deploy/frc-scheduler-server -n frc-scheduler-server -- env | grep LLM_`
- If env vars are set but button hidden, check pod logs for connection errors

If the button is visible but the badge is amber ("configured but unreachable"):
- LLM endpoint is down or behind a network barrier the cluster can't cross
- Check from a worker node: `curl -sf http://your-llm-host:8000/health`

**Without it:** the PDF import button stays hidden. Other import paths
(TBA event lookup, manual entry) still work.

**Privacy:** PDFs are sent only to the configured endpoint. If you're
self-hosting on your own infrastructure, no schedule data leaves your
network. We don't log PDF content; only file size and SHA-256 hash are
recorded for caching.

**Caching:** PDFs are cached by SHA-256 hash. Re-uploading the same file
costs zero — the cached parse is returned instantly. Cache lives in the
`pdf_imports` table; safe to truncate if you want to clear it.

**Quality expectations:**

LLM extraction is unreliable on:
- Scanned PDFs (no text layer — OCR is a separate problem)
- Heavily-stylized formats with non-tabular layouts
- PDFs with images-of-text instead of real text fragments
- Highly compressed or encrypted PDFs

The validator catches structural problems (duplicate teams, gaps in match
numbering, surrogate count mismatches) and surfaces them to the user
before commit. **Always review the preview before confirming** — LLMs
misread digits and miss surrogate notation more often than you'd hope.

**Concurrency:** the LLM endpoint typically processes one request at a
time (`--parallel 1` for llama.cpp, similar for many vLLM configs).
Multiple users importing concurrently will queue. The editor's progress
indicator updates after 15 seconds with a "may be queued" hint.

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
