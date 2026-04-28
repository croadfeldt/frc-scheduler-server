#!/usr/bin/env bash
# openshift/rebuild.sh — Full teardown and rebuild.
# Can be run from anywhere:
#   ./openshift/rebuild.sh   (from repo root)
#   ./rebuild.sh             (from inside openshift/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/config.env"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG not found. Copy config.env.example and fill in your values."
  exit 1
fi

source "$CONFIG"
source "$SCRIPT_DIR/common.sh"

: "${NAMESPACE:?Set NAMESPACE in config.env}"
: "${APP_HOSTNAME:?Set APP_HOSTNAME in config.env}"
: "${GIT_REPO_URL:?Set GIT_REPO_URL in config.env}"
: "${CERT_ISSUER:?Set CERT_ISSUER in config.env}"

GIT_BRANCH="${GIT_BRANCH:-main}"
METALLB_IP="${METALLB_IP:-}"
K8S_SERVICE_CIDR="${K8S_SERVICE_CIDR:-172.30.0.0/16}"
APP_PORT="${APP_PORT:-8443}"
CPU_WORKERS="${CPU_WORKERS:-12}"
WEB_WORKERS="${WEB_WORKERS:-1}"

NS="$NAMESPACE"


wait_for_build() {
  local BUILD="$1"
  echo "    Waiting for build $BUILD..."
  while true; do
    PHASE=$(oc get build "$BUILD" -n "$NS" \
      -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    case "$PHASE" in
      Complete)   echo "    Build $BUILD completed."; return 0 ;;
      Failed|Error|Cancelled)
        echo "    Build $BUILD failed ($PHASE)."
        oc logs "build/$BUILD" -n "$NS" --tail=40 2>/dev/null || true
        return 1 ;;
      *) echo "    Phase: $PHASE — waiting 10s..."; sleep 10 ;;
    esac
  done
}

# ── 1. Tear down ──────────────────────────────────────────────────────────────
echo "==> Tearing down all resources in namespace: $NS"
oc delete all         --all -n "$NS" --ignore-not-found
oc delete pvc         --all -n "$NS" --ignore-not-found
oc delete secret      --all -n "$NS" --ignore-not-found
oc delete configmap   --all -n "$NS" --ignore-not-found
oc delete sa          --all -n "$NS" --ignore-not-found
oc delete rolebinding --all -n "$NS" --ignore-not-found
oc delete role        --all -n "$NS" --ignore-not-found

echo ""
echo "==> Waiting for all pods to terminate..."
oc wait --for=delete pod --all -n "$NS" --timeout=60s 2>/dev/null || true

# ── 2. Refresh registry ───────────────────────────────────────────────────────
echo ""
echo "==> [pre-build] Refreshing image registry credentials..."
refresh_registry

# ── 3. Secrets ────────────────────────────────────────────────────────────────
echo ""
echo "==> [1/6] Applying secrets..."
if [ ! -f "$SCRIPT_DIR/01-secrets.yaml" ]; then
  echo "ERROR: openshift/01-secrets.yaml not found."
  echo "Copy 01-secrets.yaml.example to 01-secrets.yaml and fill in your values."
  exit 1
fi
oc apply -f "$SCRIPT_DIR/01-secrets.yaml"

# Verify DATABASE_URL is in the secret — must be set explicitly in 01-secrets.yaml
echo "    Verifying DATABASE_URL in secret..."
check_db_secret "$NS"

# Read PG_USER and PG_DB for the postgres readiness wait below.
PG_USER=$(oc get secret frc-db-secret -n "$NS" \
  -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)
PG_DB=$(oc get secret frc-db-secret -n "$NS" \
  -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)

# ── 4. Network policy ─────────────────────────────────────────────────────────
echo ""
echo "==> [1b/6] Applying network policies..."
apply_manifest "$SCRIPT_DIR/10-networkpolicy.yaml"

# ── 5. Postgres ───────────────────────────────────────────────────────────────
echo ""
echo "==> [2/6] Deploying Postgres..."
apply_manifest "$SCRIPT_DIR/02-postgres.yaml"
oc rollout status deployment/frc-postgres -n "$NS" --timeout=120s
wait_for_postgres_db "$PG_USER" "$PG_DB"

# ── 6. Certificate + Route (apply early for max cert issuance time) ───────────
echo ""
echo "==> [3/6] Applying BuildConfig + Certificate + Route..."
apply_manifest "$SCRIPT_DIR/03-buildconfig.yaml"
apply_manifest "$SCRIPT_DIR/06-certificate.yaml"
apply_manifest "$SCRIPT_DIR/05-route.yaml"
echo "    Certificate requested — cert-manager will issue in background."

# ── 7. Build ──────────────────────────────────────────────────────────────────
echo "    Waiting for builder service account..."
for i in $(seq 1 24); do
  SECRET=$(oc get sa builder -n "$NS" -o jsonpath='{.secrets[*].name}' 2>/dev/null \
           | tr ' ' '\n' | grep dockercfg | head -1)
  if [ -n "$SECRET" ]; then
    echo "    builder SA ready (secret: $SECRET)"
    break
  fi
  echo "    attempt $i/24 — waiting 5s..."
  sleep 5
done

echo "    Granting system:image-builder role to builder SA..."
oc policy add-role-to-user \
  system:image-builder \
  system:serviceaccount:"$NS":builder \
  -n "$NS"

link_builder_registry_secret "$NS"

# Refresh registry credentials immediately before starting the build.
# The credentials from the initial refresh may have rotated by the time
# the build pod is ready to push, causing authentication failures.
echo "    Refreshing registry credentials before build push..."
refresh_registry

echo ""
echo "==> Starting build..."
BUILD_NAME=$(oc start-build frc-scheduler-server-git -n "$NS" \
  -o name 2>/dev/null | sed 's|build.build.openshift.io/||')
echo "    Build started: $BUILD_NAME"
oc logs -f "build/$BUILD_NAME" -n "$NS" 2>/dev/null || true
echo ""
wait_for_build "$BUILD_NAME"

# ── 8. Deploy app ─────────────────────────────────────────────────────────────
echo ""
echo "==> [4/6] Deploying application..."
apply_manifest "$SCRIPT_DIR/04-deployment.yaml"

# Force a rollout restart so pods always pick up the latest secret values.
# Kubernetes does not automatically restart pods when referenced secrets change.
echo "    Triggering rollout restart to pick up latest secrets..."
oc rollout restart deployment/frc-scheduler-server -n "$NS"

echo "    Waiting for app rollout (300s timeout)..."
if ! oc rollout status deployment/frc-scheduler-server -n "$NS" --timeout=300s; then
  echo ""
  echo "    WARNING: App rollout did not complete within 300s."
  echo "    This is usually because the TLS certificate has not been issued yet."
  echo "    The pods will start automatically once cert-manager issues frc-scheduler-tls."
  echo ""
  echo "    Check:  oc describe certificate frc-scheduler-tls -n $NS"
  echo "    Watch:  oc get pods -n $NS -w"
fi

# ── 9. CronJob + RBAC ─────────────────────────────────────────────────────────
echo ""
echo "==> [6/6] Applying build CronJob and RBAC..."
apply_manifest "$SCRIPT_DIR/07-build-trigger-sa.yaml"
apply_manifest "$SCRIPT_DIR/08-build-cronjob.yaml"

# ── 10. Verify ────────────────────────────────────────────────────────────────
echo ""
echo "==> Rebuild complete."
oc get pods    -n "$NS"
oc get cronjob -n "$NS"
echo ""
HOST=$(oc get route frc-scheduler-server -n "$NS" \
  -o jsonpath='{.spec.host}' 2>/dev/null || echo "(route not yet ready)")
echo "App URL: https://$HOST"
