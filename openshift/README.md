# OpenShift Deployment

## Prerequisites
- `oc` CLI logged in to your cluster
- cert-manager operator installed with a ClusterIssuer configured
- MetalLB configured with a BGP address pool
- DNS for your hostname pointing at the MetalLB VIP

## First-time setup

### 1. Configure site-specific values
```sh
cp config.env.example config.env
# Edit config.env — fill in GIT_REPO_URL, APP_HOSTNAME, CERT_ISSUER, METALLB_IP
```

### 2. Create secrets (once — never committed to git)
```sh
cp 01-secrets.yaml.example 01-secrets.yaml
# Edit 01-secrets.yaml — fill in real passwords, API keys, JWT secret
oc apply -f 01-secrets.yaml
rm 01-secrets.yaml   # do not leave real secrets on disk
```

### 3. Apply all manifests
```sh
./apply.sh
```

### 4. Wait for cert issuance
```sh
oc get certificate frc-scheduler-tls -n frc-scheduler-server -w
```

### 5. Trigger first build
```sh
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
```

### 6. Configure external integrations (TBA, Nexus, etc.)
The scheduler talks to several external services — TBA for event data,
Nexus for live queue updates, Statbotics for EPA stats, and others. Each
integration's setup, what it does, and what configuration it needs is
documented separately:

> 📖 See **[`docs/INTEGRATIONS.md`](../docs/INTEGRATIONS.md)** for full setup of every integration.

Most integrations need only an entry in `01-secrets.yaml`. The Nexus
webhook setup additionally requires configuring the webhook URL inside
Nexus's own dashboard — that walkthrough is in the integrations doc.

## Files

| File | Purpose | Committed? |
|------|---------|-----------|
| `config.env.example` | Template — copy to `config.env` | ✓ yes |
| `config.env` | Your real hostnames/URLs | ✗ gitignored |
| `01-secrets.yaml.example` | Template — copy to `01-secrets.yaml` | ✓ yes |
| `01-secrets.yaml` | Your real secrets | ✗ gitignored |
| `apply.sh` | Substitutes config values and applies manifests | ✓ yes |
| `00-namespace.yaml` | Namespace | ✓ yes |
| `02-postgres.yaml` | PostgreSQL StatefulSet | ✓ yes |
| `03-buildconfig.yaml` | ImageStream + BuildConfig | ✓ yes |
| `04-deployment.yaml` | Deployment + ClusterIP + LoadBalancer + PDB | ✓ yes |
| `05-route.yaml` | OpenShift Route (passthrough TLS) | ✓ yes |
| `07-build-trigger-sa.yaml` | ServiceAccount for build CronJob | ✓ yes |
| `08-build-cronjob.yaml` | Git-poll CronJob for auto-builds | ✓ yes |
| `09-certificate.yaml` | cert-manager Certificate (Let's Encrypt) | ✓ yes |
| `09-hpa-optional.yaml` | HorizontalPodAutoscaler (optional) | ✓ yes |
| `10-networkpolicy.yaml` | Pod network isolation | ✓ yes |

## TLS flow

```
cert-manager → issues cert → stores in Secret 'frc-scheduler-tls'
                                        ↓
Deployment mounts Secret at /certs/tls.crt + tls.crt.key
                                        ↓
entrypoint.sh passes --ssl-certfile/--ssl-keyfile to uvicorn
                                        ↓
stakater/Reloader restarts pods on cert renewal (automatic)
```

## Rebuilding after code changes

Builds are triggered automatically every 5 minutes by the CronJob if new commits are detected. To trigger manually:
```sh
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
```
