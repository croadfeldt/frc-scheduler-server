# OAuth Provider Setup

**Repository:** `github.com/croadfeldt/frc-scheduler-server`
**Document type:** Operator runbook
**Audience:** Whoever deploys or maintains the server
**Companion docs:**
- `AUTH_DESIGN.md` — authentication model + endpoint enforcement
- `workstreams/schedule-lifecycle.md` — what authentication enables (audit, locks, freeze)

This document is the step-by-step for configuring Google and Apple
sign-in. The codebase already implements both providers in
`app/auth.py`; this doc covers the external setup needed at the
provider's developer console plus the environment variables the
server expects.

---

## Overview

The server supports two sign-in providers, each requiring its own
OAuth credentials:

| Provider | Required env vars                                                       | Console                                                                  |
|----------|-------------------------------------------------------------------------|--------------------------------------------------------------------------|
| Google   | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`                              | [Google Cloud Console — Credentials](https://console.cloud.google.com/apis/credentials) |
| Apple    | `APPLE_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` | [Apple Developer — Identifiers](https://developer.apple.com/account/resources/identifiers/list/serviceId) |

Common to both:

| Env var       | Purpose                                                                                            | Example                                          |
|---------------|----------------------------------------------------------------------------------------------------|--------------------------------------------------|
| `BASE_URL`    | Public URL of the server. Used to build callback URIs and JWT postMessage `targetOrigin`.          | `https://frc-scheduler.roadfeldt.com`            |
| `JWT_SECRET`  | HMAC signing key for session tokens. Must be a stable random value across restarts.                | (32+ random bytes; rejected if left at default)  |

The callback URLs the providers need to allow are derived from
`BASE_URL` — they are NOT separate env vars. Whatever you set
`BASE_URL` to, the callback paths are appended:

```
{BASE_URL}/auth/google/callback
{BASE_URL}/auth/apple/callback
```

If your production `BASE_URL` is `https://frc-scheduler.roadfeldt.com`,
then the URLs to register with the providers are:

```
https://frc-scheduler.roadfeldt.com/auth/google/callback
https://frc-scheduler.roadfeldt.com/auth/apple/callback
```

For local development, with `BASE_URL=http://localhost:8000`:

```
http://localhost:8000/auth/google/callback
http://localhost:8000/auth/apple/callback
```

You can register both production and local callbacks with each
provider so the same OAuth credentials work in both environments.

---

## Google sign-in setup

### 1. Create or open a Google Cloud project

Visit https://console.cloud.google.com/ and either select an
existing project or create a new one. The project name is internal
— users never see it. Suggested name: "FRC Scheduler" or your org's
name.

### 2. Configure the OAuth consent screen

Navigate: **APIs & Services → OAuth consent screen**

- **User Type:** External (unless you're using Google Workspace and
  want to limit to your org's domain — Internal in that case).
- **App information:**
  - App name: e.g. "FRC Scheduler"
  - User support email: your email
  - App logo: optional
- **App domain:**
  - Application home page: `{BASE_URL}` (e.g.
    `https://frc-scheduler.roadfeldt.com`)
  - Privacy policy link: optional but recommended
  - Terms of service link: optional
- **Authorized domains:** add the bare domain (no scheme, no path).
  For `https://frc-scheduler.roadfeldt.com`, add `roadfeldt.com`.
  For local-only development you can skip this — Google allows
  `localhost` without explicit registration.
- **Developer contact information:** your email
- **Scopes:** click **Add or remove scopes** and select:
  - `.../auth/userinfo.email`
  - `.../auth/userinfo.profile`
  - `openid`

These three scopes are what the server requests; granting them
gives us the user's `sub` (stable identifier), `email`, and `name`.

- **Test users:** if your app is in "Testing" status (default for
  External user-type until you publish), only test users you list
  here can sign in. Add yourself and anyone else who needs access
  during development.

Save. Submit the app for verification only when you're ready to
let arbitrary external users sign in — for a single-org tool, you
can stay in Testing indefinitely with up to 100 test users.

### 3. Create OAuth credentials

Navigate: **APIs & Services → Credentials → Create Credentials → OAuth client ID**

- **Application type:** Web application
- **Name:** anything descriptive, e.g. "FRC Scheduler Server"
- **Authorized JavaScript origins:** add the origin (no path):
  - `https://frc-scheduler.roadfeldt.com`
  - `http://localhost:8000` (for local dev, optional)
- **Authorized redirect URIs:** add the full callback URLs:
  - `https://frc-scheduler.roadfeldt.com/auth/google/callback`
  - `http://localhost:8000/auth/google/callback` (for local dev,
    optional)

Click **Create**. You'll see a dialog with:

- **Client ID** — long string ending in
  `.apps.googleusercontent.com`. Goes into `GOOGLE_CLIENT_ID`.
- **Client Secret** — alphanumeric string. Goes into
  `GOOGLE_CLIENT_SECRET`.

Copy both. The secret is shown only at creation time — if you lose
it, generate a new one (which invalidates the old one).

### 4. Set environment variables

Whichever way your deployment manages env vars (OpenShift secret,
.env file, k8s ConfigMap):

```
GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-AbCdEfGhIjKlMnOpQrStUvWxYz
BASE_URL=https://frc-scheduler.roadfeldt.com
```

For OpenShift specifically:

```bash
oc create secret generic frc-scheduler-google-oauth \
  --from-literal=GOOGLE_CLIENT_ID="123456789-abcdefg.apps.googleusercontent.com" \
  --from-literal=GOOGLE_CLIENT_SECRET="GOCSPX-AbCdEfGhIjKlMnOpQrStUvWxYz"

# Then mount as env in the deployment manifest, or:
oc set env deployment/frc-scheduler-server --from=secret/frc-scheduler-google-oauth
```

Restart the pod / process for the env vars to take effect.

### 5. Test

Visit `{BASE_URL}/auth/google/login`. The flow:

1. Redirects to Google's OAuth consent screen
2. You sign in and grant the requested scopes
3. Google redirects back to `{BASE_URL}/auth/google/callback?code=...`
4. Server exchanges the code for tokens, creates or updates a
   `users` row, issues a JWT
5. JWT is delivered to the opener window via `postMessage` (or
   localStorage fallback for non-popup flows)

If you see a `redirect_uri_mismatch` error, the URI registered in
the Google Console doesn't match what the server is sending —
check that `BASE_URL` is set correctly and that the callback URI
in step 3 is in the Authorized redirect URIs list.

---

## Apple sign-in setup

Apple's setup is more involved than Google's because Apple uses a
JWT-based client secret rather than a static one, and they
distinguish between "App IDs" and "Service IDs."

### 1. Apple Developer Program membership

Required. $99/year. If you don't have one, this is the first cost.
Sign in at https://developer.apple.com/account/.

### 2. Create an App ID

Navigate: **Certificates, Identifiers & Profiles → Identifiers → +**

- Select **App IDs** → Continue
- **Type:** App
- **Description:** e.g. "FRC Scheduler"
- **Bundle ID:** Explicit, e.g. `com.roadfeldt.frcscheduler` (this
  is just an identifier; it doesn't have to match anything real)
- **Capabilities:** scroll to **Sign In with Apple** and check it
- Continue → Register

The App ID is a prerequisite for the Service ID; you won't use the
App ID's identifier directly in your env vars.

### 3. Create a Service ID (the actual `APPLE_CLIENT_ID`)

Navigate: **Identifiers → +**

- Select **Services IDs** → Continue
- **Description:** e.g. "FRC Scheduler Web Sign-In"
- **Identifier:** e.g. `com.roadfeldt.frcscheduler.web` — this is
  what goes into `APPLE_CLIENT_ID`
- Continue → Register

After registration, click the new Service ID to edit it:

- Check **Sign In with Apple**
- Click **Configure**
  - **Primary App ID:** select the App ID you created in step 2
  - **Domains and Subdomains:** the bare domain, e.g.
    `frc-scheduler.roadfeldt.com` (no scheme, no path). For
    localhost development, Apple does NOT accept `localhost` —
    you'll need a public-facing dev environment or a tunnel
    service like ngrok.
  - **Return URLs:** the full callback URL:
    `https://frc-scheduler.roadfeldt.com/auth/apple/callback`
  - Click **Next** → **Done** → **Continue** → **Save**

Apple verifies the domain by serving a well-known file. They'll
prompt you to download `apple-developer-domain-association.txt`
and host it at:

```
https://{your-domain}/.well-known/apple-developer-domain-association
```

The server has a route for this at
`GET /.well-known/apple-developer-domain-association`, controlled by
the `APPLE_DOMAIN_ASSOCIATION_FILE` env var. The route returns 404
when the env var is unset or points at a missing file (the default
on a deployment that isn't using Apple sign-in). For OpenShift
deployments, use the ConfigMap pattern below; for other
environments, set `APPLE_DOMAIN_ASSOCIATION_FILE` to any path
where the file is readable by the server process.

Verify the domain in the Apple console after the file is
reachable. Verification is required before sign-in works.

#### OpenShift deployment of the domain-association file

The repository's deployment manifest already supports this case
through an optional ConfigMap. The path:

1. Download the domain-association file from the Apple Developer
   portal (the prompt during Service ID configuration). The file
   has no extension — Apple ships it named
   `apple-developer-domain-association.txt`. **Rename it on disk**
   to drop the `.txt` extension before uploading; the file the
   server serves and the URL Apple verifies must both end in
   `apple-developer-domain-association` (no extension).

   ```bash
   mv apple-developer-domain-association.txt apple-developer-domain-association
   ```

2. Create a ConfigMap from the file. The ConfigMap key name must
   be exactly `apple-developer-domain-association` — the deployment
   mounts the ConfigMap at
   `/etc/apple-domain-association/` and the server reads
   `/etc/apple-domain-association/apple-developer-domain-association`.

   ```bash
   oc create configmap frc-apple-domain-association \
     --from-file=apple-developer-domain-association=./apple-developer-domain-association
   ```

   If you need to update the file later (Apple regenerated it,
   key rotation, etc.):

   ```bash
   oc delete configmap frc-apple-domain-association
   oc create configmap frc-apple-domain-association \
     --from-file=apple-developer-domain-association=./apple-developer-domain-association
   oc rollout restart deployment/frc-scheduler-server
   ```

3. **You don't need to redeploy the manifest if the deployment
   already shipped with the optional volume in place.** The
   `optional: true` flag on the volume means the pod runs whether
   the ConfigMap exists or not; creating the ConfigMap and
   restarting the pod is enough.

4. After the pod restarts, verify the file is reachable from the
   public internet:

   ```bash
   curl -I https://frc-scheduler.roadfeldt.com/.well-known/apple-developer-domain-association
   # Expect: HTTP/2 200 ... content-type: text/plain
   ```

   If you get 404, check:
   - Did the ConfigMap get created? `oc get configmap frc-apple-domain-association`
   - Did the pod restart after the ConfigMap was created?
     `oc rollout restart deployment/frc-scheduler-server`
   - Is `APPLE_DOMAIN_ASSOCIATION_FILE` env var set in the pod?
     `oc rsh deployment/frc-scheduler-server env | grep APPLE_DOMAIN`
   - Is the file mounted? `oc rsh deployment/frc-scheduler-server ls /etc/apple-domain-association/`

5. Once the file is reachable with HTTP 200 and `text/plain`,
   click **Verify** in the Apple Developer portal Service ID
   page. Verification usually completes within a minute.

### 4. Create a Sign In with Apple key

Navigate: **Keys → +**

- **Key Name:** e.g. "FRC Scheduler Sign-In Key"
- **Capabilities:** check **Sign In with Apple**
- Click **Configure** next to Sign In with Apple
  - **Primary App ID:** the App ID from step 2
  - Save
- Continue → Register → **Download** the `.p8` key file

**Important:** the .p8 file can only be downloaded once. Store it
securely.

Note the **Key ID** shown on the registration page — this goes
into `APPLE_KEY_ID`. It's a 10-character alphanumeric string.

### 5. Find your Team ID

Visit https://developer.apple.com/account → **Membership** in the
sidebar. The **Team ID** is a 10-character alphanumeric string.
Goes into `APPLE_TEAM_ID`.

### 6. Set environment variables

```
APPLE_CLIENT_ID=com.roadfeldt.frcscheduler.web
APPLE_TEAM_ID=ABCDE12345
APPLE_KEY_ID=FGHIJ67890
APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----
MIGTAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBHkwdwIBAQQg...
-----END PRIVATE KEY-----"
BASE_URL=https://frc-scheduler.roadfeldt.com
```

The private key is the contents of the .p8 file you downloaded.
Multi-line values can be tricky in env-var configurations — the
server supports both literal newlines and escaped `\n` sequences
(it does `APPLE_PRIVATE_KEY.replace("\\n", "\n")` before use).

For OpenShift:

```bash
# .p8 file must be passed as a literal value with newlines preserved
oc create secret generic frc-scheduler-apple-oauth \
  --from-literal=APPLE_CLIENT_ID="com.roadfeldt.frcscheduler.web" \
  --from-literal=APPLE_TEAM_ID="ABCDE12345" \
  --from-literal=APPLE_KEY_ID="FGHIJ67890" \
  --from-file=APPLE_PRIVATE_KEY=AuthKey_FGHIJ67890.p8

oc set env deployment/frc-scheduler-server --from=secret/frc-scheduler-apple-oauth
```

The `--from-file` form is the cleanest way to handle the multi-line
key — the file's contents become the value verbatim, no escaping
needed.

### 7. Test

Visit `{BASE_URL}/auth/apple/login`. The flow:

1. Redirects to Apple's authorize URL
2. You sign in with your Apple ID and authorize the app
3. Apple POSTs back to `{BASE_URL}/auth/apple/callback` (note: POST,
   not GET — Apple uses `response_mode=form_post`)
4. Server exchanges the code for tokens, validates the ID token's
   signature against Apple's JWKS, creates or updates a `users`
   row, issues a JWT
5. JWT delivered to opener via `postMessage`

Common errors:

- **`invalid_client`** — usually means `APPLE_CLIENT_ID` doesn't
  match a registered Service ID, or the Service ID isn't
  associated with the App ID, or domain verification hasn't
  completed.
- **`invalid_grant`** — the authorization code expired (they're
  one-time-use, ~10 min lifetime) or was already exchanged.
- **JWT signature errors during code exchange** — `APPLE_TEAM_ID`,
  `APPLE_KEY_ID`, or `APPLE_PRIVATE_KEY` is wrong; the server
  builds a JWT signed with these to authenticate to Apple.

---

## Both providers — common configuration

### `BASE_URL`

This is the single most important variable for OAuth to work. The
server uses it for three things:

1. Constructing the `redirect_uri` sent to the OAuth provider
2. Constructing the `targetOrigin` for `postMessage` token delivery
3. Constructing absolute URLs in OAuth flows

If `BASE_URL` doesn't match what the user's browser sees, OAuth
will fail with `redirect_uri_mismatch`. Set it to the public-facing
URL, including scheme. **No trailing slash.**

```
✓ BASE_URL=https://frc-scheduler.roadfeldt.com
✗ BASE_URL=https://frc-scheduler.roadfeldt.com/
✗ BASE_URL=frc-scheduler.roadfeldt.com
```

### `JWT_SECRET`

The HMAC key used to sign session tokens. Treat it like a database
password.

- Must be at least 32 bytes (the server warns on shorter values)
- Must be stable across pod restarts — changing it invalidates all
  existing sessions, forcing every user to sign in again
- The server **refuses to start in production mode** if
  `JWT_SECRET=change-me-in-production` (the default)

Generate one with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

For OpenShift:

```bash
oc create secret generic frc-scheduler-jwt \
  --from-literal=JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

oc set env deployment/frc-scheduler-server --from=secret/frc-scheduler-jwt
```

### `ADMIN_EMAILS` (when shipping `is_admin` Phase E)

Once Phase E of `workstreams/schedule-lifecycle.md` ships, this env var
designates which users get the `is_admin=true` flag set on login.

```
ADMIN_EMAILS=alice@example.com,bob@example.com
```

The flag is set by `upsert_user()` during the OAuth callback flow.
Adding an email here causes that user to gain admin status on their
next login. Removing an email does NOT auto-revoke — that requires
a database update (intentional: prevents accidental lockout from a
config typo).

### Multiple environments

If you want both production and a staging/dev environment to share
OAuth credentials, register all the callback URLs with each
provider:

Google: add all in **Authorized redirect URIs**.
Apple: add all in the Service ID's **Return URLs**.

Each environment sets its own `BASE_URL` and the appropriate
callback URL gets used automatically. If your dev environment is
on `localhost`, you can do this with Google but not Apple — Apple
requires a real domain. Workarounds for Apple local dev: a tunnel
service like ngrok with a stable subdomain, or a separate dev-only
Service ID pointing at a publicly-resolvable dev URL.

---

## Verifying the setup end-to-end

After configuring both providers, test each flow:

```
1. Visit {BASE_URL} (or any page that shows the sign-in button)
2. Click "Sign in with Google"
3. Complete Google OAuth
4. Confirm you land back on the app, signed in
5. Visit {BASE_URL}/auth/me — should return JSON with your sub,
   email, provider="google"
6. Sign out (if there's a UI for it) or clear cookies
7. Click "Sign in with Apple"
8. Complete Apple OAuth
9. Confirm /auth/me now reports provider="apple"
```

For Apple specifically, the first sign-in for a given Apple ID
will prompt you to choose whether to share or hide your email. The
hidden-email flow returns a relay address (`@privaterelay.appleid.com`)
which the server stores as-is.

---

## Troubleshooting

| Symptom                                         | Likely cause                                                                                  |
|-------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `redirect_uri_mismatch` (Google)                | Callback URL not registered, or `BASE_URL` doesn't match the URL the browser is using         |
| `invalid_client` (Apple)                        | Service ID doesn't match `APPLE_CLIENT_ID`, or domain verification incomplete                 |
| Token delivery fails silently in browser console | Browser blocks `postMessage` from a different origin — `BASE_URL` mismatch                    |
| 500 error during code exchange (Apple)          | `APPLE_PRIVATE_KEY` env var has escaped newlines incorrectly; check via `oc rsh` + `env`      |
| Server refuses to start                         | `JWT_SECRET` left at default, or set to less than 32 bytes                                    |
| User signs in successfully but `users` row not created | Database connectivity issue at upsert time; check application logs                            |
| Login redirects in a loop                       | JWT cookie / localStorage delivery failed; usually a `targetOrigin` mismatch — check `BASE_URL` |

### Apple `400 Bad Request` from `/auth/token`

The server now surfaces Apple's actual error code in the response —
look for messages like `Apple token endpoint returned 400:
invalid_client (...)` in the JSON `detail` field or the server logs.
The most common causes, in rough order:

1. **`APPLE_CLIENT_ID` is the App ID, not the Service ID.** The App
   ID looks like `com.example.app` and is the *bundle identifier*.
   The Service ID looks similar (often `com.example.app.web`) but
   is a separate object in the developer portal under
   **Identifiers → Services IDs**. The Service ID is what the
   web flow uses; the App ID is for native iOS apps. Mixing them
   produces an opaque `invalid_client`.

2. **Whitespace in env-var values.** OpenShift's secret editor
   often adds trailing newlines when pasting from a webpage. The
   server now whitespace-strips `APPLE_TEAM_ID`, `APPLE_KEY_ID`,
   `APPLE_CLIENT_ID`, and `BASE_URL` at load time. If your
   diagnostic still points at one of these, verify the actual
   pod-side value:

   ```bash
   oc rsh deployment/frc-scheduler-server python3 -c \
     "import os; v=os.getenv('APPLE_CLIENT_ID',''); print(repr(v))"
   ```

   Trailing `\n` would show as `'com.example.app.web\n'` — easy
   to miss in shell output, obvious in `repr()`.

3. **Key not associated with the App ID.** The Sign In with Apple
   key (the .p8 file) must be linked to a primary App ID in the
   developer portal. If you generated the key without selecting an
   App ID, it can't sign client secrets for any Service ID.
   Re-check **Keys → (your key) → Configure → Primary App ID** in
   the portal. If it's empty, fix it (you may need to regenerate
   the key — the binding can't always be edited after creation).

4. **Service ID not associated with the App ID.** Symmetric to #3.
   In the portal, **Identifiers → (Service ID) → Sign In with
   Apple → Configure → Primary App ID** must point at the App ID
   the key is bound to.

5. **`APPLE_PRIVATE_KEY` is incomplete or malformed.** The .p8
   file has a `-----BEGIN PRIVATE KEY-----` line, a base64 body,
   and `-----END PRIVATE KEY-----`. All three are required. The
   server logs `Apple client secret: APPLE_PRIVATE_KEY does not
   contain 'BEGIN PRIVATE KEY'` when the wrappers are missing.

6. **`APPLE_TEAM_ID` mismatch.** The 10-character team ID from
   the developer portal Membership page. If you have multiple
   Apple Developer teams, confirm you're using the team that owns
   the App ID and Service ID.

7. **Domain verification incomplete.** Apple won't issue
   credentials for a Service ID whose domain isn't verified.
   Check `https://YOUR_HOST/.well-known/apple-developer-domain-association`
   returns 200 with `text/plain`, then click **Verify** in the
   portal. The token endpoint may keep returning `invalid_client`
   for a few minutes after verification completes.

8. **`code` reused or expired.** Apple authorization codes are
   one-time-use and live ~10 minutes. Hitting the callback twice
   (e.g., from a stuck retry) produces `invalid_grant` not
   `invalid_client`, but the symptom is the same 400.

The diagnostic flow:

```bash
# 1. See the actual Apple error code and description in the logs
oc logs -l app=frc-scheduler-server-git --tail=200 | grep -i apple

# 2. Confirm the four env vars are present, no whitespace, no defaults
oc rsh deployment/frc-scheduler-server python3 -c "
import os
for k in ['APPLE_CLIENT_ID','APPLE_TEAM_ID','APPLE_KEY_ID']:
    v = os.getenv(k,'')
    print(f'{k}: {repr(v)}  len={len(v)}')
print('APPLE_PRIVATE_KEY first line:',
      repr(os.getenv('APPLE_PRIVATE_KEY','').splitlines()[:1]))
print('BEGIN PRIVATE KEY' in os.getenv('APPLE_PRIVATE_KEY',''))
"

# 3. Confirm domain-association file is reachable
curl -I https://YOUR_HOST/.well-known/apple-developer-domain-association
```

For deeper diagnostics, the server logs OAuth errors at WARNING
level. Fetch with:

```bash
oc logs -l app=frc-scheduler-server-git --tail=100 | grep -i "oauth\|jwt\|auth"
```

---

## Security notes

The implementation in `app/auth.py` already takes the following
precautions:

- JWT delivery via `postMessage` uses `targetOrigin=BASE_URL`, never
  `*` — only our origin can receive the token
- Token strings embedded in HTML are JSON-encoded so quotes,
  backslashes, and Unicode line terminators (U+2028/U+2029) can't
  break out of the script context
- Frontend validates the `postMessage` origin matches
  `window.location.origin` before accepting the token
- The JWT default secret is rejected at startup; production
  deployments must override it
- Apple ID tokens are validated against Apple's JWKS at code
  exchange time — the server doesn't trust the ID token sent
  alongside the code without verifying its signature

If you find a security issue with the OAuth implementation, file
it through the repository's normal issue process.
