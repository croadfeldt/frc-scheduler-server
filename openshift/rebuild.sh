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

source "$SCRIPT_DIR/common.sh"


refresh_registry() {
  echo "    Refreshing image registry operator (NooBaa credential reconcile)..."
  oc patch configs.imageregistry.operator.openshift.io cluster \
    --type merge --patch '{"spec":{"managementState":"Removed"}}' 2>/dev/null || true
  sleep 15
  oc patch configs.imageregistry.operator.openshift.io cluster \
    --type merge --patch '{"spec":{"managementState":"Managed"}}' 2>/dev/null || true
  echo "    Waiting for registry deployment to be available..."
  for i in $(seq 1 24); do
    if oc get deployment image-registry -n openshift-image-registry > /dev/null 2>&1; then
      break
    fi
    echo "    attempt $i/24 — waiting 5s..."
    sleep 5
  done
  echo "    Waiting for registry rollout..."
  oc rollout status deployment/image-registry \
    -n openshift-image-registry --timeout=120s 2>/dev/null || true
  echo "    Registry ready."
}

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

# Wait for the POSTGRES_DB database to actually exist and accept queries.
# pg_isready returns success as soon as postgres accepts connections — before
# initdb has finished creating the POSTGRES_DB database. This explicit check
# prevents the app deployment from racing postgres initialization.

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
oc apply -f "$SCRIPT_DIR/01-secrets.yaml"

# Read the DB credentials from the secret we just applied.
PG_USER=$(oc get secret frc-db-secret -n "$NS" \
  -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)
PG_DB=$(oc get secret frc-db-secret -n "$NS" \
  -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)
PG_PASS=$(oc get secret frc-db-secret -n "$NS" \
  -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)

# Ensure DATABASE_URL is in the secret — Kubernetes $(VAR) interpolation does
# not work when the referenced var comes from valueFrom: secretKeyRef.
# We patch it here from the component values so it's always consistent.
DB_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@frc-postgres:5432/${PG_DB}"
_TMP=$(mktemp /tmp/db-url-patch-XXXXXX.yaml)
printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: frc-db-secret\n  namespace: %s\nstringData:\n  DATABASE_URL: "%s"\n' "${NS}" "${DB_URL}" > "$_TMP"
oc apply -f "$_TMP"
rm -f "$_TMP"
echo "    DATABASE_URL patched into frc-db-secret"

# ── 4. Network policy ─────────────────────────────────────────────────────────
echo ""
echo "==> [1b/6] Applying network policies..."
apply_manifest "$SCRIPT_DIR/10-networkpolicy.yaml"

# ── 5. Postgres ───────────────────────────────────────────────────────────────
echo ""
echo "==> [2/6] Deploying Postgres..."
apply_manifest "$SCRIPT_DIR/02-postgres.yaml"

# Wait for the pod to be running first
oc rollout status deployment/frc-postgres -n "$NS" --timeout=120s

# Then wait for the actual database to exist — rollout status returns as soon
# as the readiness probe passes, which now verifies the DB exists. But we also
# do an explicit check here as a belt-and-suspenders guard.
wait_for_postgres_db "$PG_USER" "$PG_DB"

# ── 6. Build ──────────────────────────────────────────────────────────────────
echo ""
echo "==> [3/6] Applying BuildConfig..."
apply_manifest "$SCRIPT_DIR/03-buildconfig.yaml"

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

echo ""
echo "==> Starting build..."
BUILD_NAME=$(oc start-build frc-scheduler-server-git -n "$NS" \
  -o name 2>/dev/null | sed 's|build.build.openshift.io/||')
echo "    Build started: $BUILD_NAME"
oc logs -f "build/$BUILD_NAME" -n "$NS" 2>/dev/null || true
echo ""
wait_for_build "$BUILD_NAME"

# ── 7. Deploy app ─────────────────────────────────────────────────────────────
echo ""
echo "==> [4/6] Deploying application..."
apply_manifest "$SCRIPT_DIR/04-deployment.yaml"
oc rollout status deployment/frc-scheduler-server -n "$NS" --timeout=300s

# ── 8. Route ──────────────────────────────────────────────────────────────────
echo ""
echo "==> [5/6] Applying route..."
apply_manifest "$SCRIPT_DIR/05-route.yaml"

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
