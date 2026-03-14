# OpenShift Deployment

Complete deployment config for OpenShift 4.x. Files are numbered in apply order.

## Prerequisites

- `oc` CLI logged in: `oc login https://api.your-cluster.example.com`
- Access to build images (cluster-admin or self-provisioner role)
- If using `registry.redhat.io/rhel9/postgresql-16`, ensure your cluster has a
  Red Hat registry pull secret. If not, swap the image for `docker.io/library/postgres:16-alpine`
  and change the env var names from `POSTGRESQL_*` to `POSTGRES_*` in `02-postgres.yaml`.

## Quick deploy

```bash
# 1. Create the project
oc new-project frc-scheduler

# 2. Edit secrets before applying
#    Set POSTGRES_PASSWORD and TBA_API_KEY in 01-secrets.yaml

# 3. Apply everything in order
oc apply -f openshift/00-namespace.yaml
oc apply -f openshift/01-secrets.yaml
oc apply -f openshift/02-postgres.yaml
oc apply -f openshift/03-buildconfig.yaml
oc apply -f openshift/04-deployment.yaml
oc apply -f openshift/05-route.yaml
oc apply -f openshift/06-hpa.yaml   # optional

# 4. Build and push the image from local source
oc start-build frc-scheduler-build --from-dir=. --follow -n frc-scheduler

# 5. Watch the rollout
oc rollout status deployment/frc-scheduler -n frc-scheduler

# 6. Get the public URL
oc get route frc-scheduler -n frc-scheduler -o jsonpath='{.spec.host}'
```

## Applying all at once

```bash
oc apply -f openshift/
oc start-build frc-scheduler-build --from-dir=. --follow -n frc-scheduler
```

## Build from Git (CI/CD)

Edit `03-buildconfig.yaml`, uncomment the Git source block, and set your repo URL.
Every `git push` can then trigger a rebuild via a webhook:

```bash
# Get the GitHub webhook URL
oc describe bc/frc-scheduler-build -n frc-scheduler | grep -A2 "GitHub"
```

Add the webhook URL + secret to your GitHub repo under Settings → Webhooks.

## Image registry

The BuildConfig outputs to the internal OpenShift registry via the `frc-scheduler`
ImageStream. The Deployment references `frc-scheduler:latest` which resolves
through the ImageStream's `lookupPolicy.local: true`.

If you prefer an external registry (Quay, Docker Hub, etc.):

1. Change the BuildConfig `spec.output.to` to an `DockerImage` reference
2. Create a push secret and reference it in the BuildConfig
3. Update the Deployment image to the full external reference

## Postgres image

The default is `registry.redhat.io/rhel9/postgresql-16` (Red Hat UBI-based,
certified for OpenShift). If you don't have Red Hat registry credentials:

```yaml
# In 02-postgres.yaml, replace the image line with:
image: docker.io/library/postgres:16-alpine
# And change env var names from POSTGRESQL_* to POSTGRES_*
```

## Updating the app

```bash
# Rebuild from local source
oc start-build frc-scheduler-build --from-dir=. --follow -n frc-scheduler

# Or trigger from Git (if configured)
oc start-build frc-scheduler-build --follow -n frc-scheduler
```

## Scaling

```bash
# Manual scale
oc scale deployment/frc-scheduler --replicas=2 -n frc-scheduler

# The HPA (06-hpa.yaml) auto-scales 1-4 replicas at 70% CPU.
# For maximum scheduling parallelism, prefer a single pod with high CPU limits
# over many small pods, since ProcessPoolExecutor workers are per-pod.
```

## Logs and debugging

```bash
oc logs -f deployment/frc-scheduler -n frc-scheduler
oc logs -f deployment/frc-postgres  -n frc-scheduler
oc exec -it deployment/frc-scheduler -n frc-scheduler -- /bin/bash
```
