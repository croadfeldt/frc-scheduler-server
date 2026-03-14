# OpenShift Deployment — frc-scheduler-server

## Namespace
`frc-scheduler-server`

## Apply order

```bash
# 1. Project should already exist. If not:
oc new-project frc-scheduler-server

# 2. Populate secrets first (edit values before applying)
#    - 01-secrets.yaml: set POSTGRES_PASSWORD, TBA_API_KEY, git-contents-token
oc apply -f openshift/01-secrets.yaml

# 3. Postgres
oc apply -f openshift/02-postgres.yaml
oc rollout status deployment/frc-postgres -n frc-scheduler-server

# 4. ImageStream + BuildConfig
oc apply -f openshift/03-buildconfig.yaml

# 5. Trigger first build manually
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server

# 6. Deploy app + service
oc apply -f openshift/04-deployment.yaml
oc rollout status deployment/frc-scheduler-server -n frc-scheduler-server

# 7. Route (external HTTPS access)
oc apply -f openshift/05-route.yaml
oc get route frc-scheduler-server -n frc-scheduler-server -o jsonpath='{.spec.host}'

# 8. Build trigger RBAC + CronJob (polls GitHub every 5 min)
oc apply -f openshift/07-build-trigger-sa.yaml
oc apply -f openshift/08-build-cronjob.yaml

# Optional: HPA (auto-scales 1-4 replicas at 70% CPU)
# oc apply -f openshift/09-hpa-optional.yaml
```

## Apply everything at once (after editing secrets)
```bash
oc apply -f openshift/
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
```

## File reference
| File | Contents |
|------|----------|
| 00-namespace.yaml | Project namespace |
| 01-secrets.yaml | DB creds, TBA key, GitHub PAT |
| 02-postgres.yaml | PVC + Deployment + Service for Postgres |
| 03-buildconfig.yaml | ImageStream + BuildConfig (GitHub source, Containerfile) |
| 04-deployment.yaml | App Deployment + ClusterIP Service |
| 05-route.yaml | HTTPS Route (edge TLS termination) |
| 07-build-trigger-sa.yaml | ServiceAccount + RBAC for CronJob |
| 08-build-cronjob.yaml | git-commit-hash ConfigMap + polling CronJob |
| 09-hpa-optional.yaml | HorizontalPodAutoscaler (optional) |

## Build trigger
Builds are triggered by the `git-poll-trigger` CronJob every 5 minutes.
It compares the latest GitHub commit hash against the `git-commit-hash` ConfigMap
and calls `oc start-build` only when a change is detected.

Manual trigger:
```bash
oc start-build frc-scheduler-server-git --follow -n frc-scheduler-server
```

## Naming conventions (matches OpenShift web console generated names)
- ImageStream: `frc-scheduler-server-git`
- BuildConfig: `frc-scheduler-server-git`
- Deployment:  `frc-scheduler-server`
- Service:     `frc-scheduler-server`
- Route:       `frc-scheduler-server`

## Secrets to populate before applying
| Secret | Key | Value |
|--------|-----|-------|
| frc-db-secret | POSTGRES_PASSWORD | Choose a strong password |
| frc-app-secret | TBA_API_KEY | From https://www.thebluealliance.com/account |
| git-contents-token | token | GitHub PAT with read:contents scope |
