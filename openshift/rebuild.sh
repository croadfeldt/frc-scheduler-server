#!/usr/bin/env bash
# openshift/rebuild.sh — Full teardown and rebuild of the frc-scheduler-server namespace.
#
# Can be run from anywhere:
#   ./openshift/rebuild.sh        (from repo root)
#   ./rebuild.sh                  (from inside openshift/)
#   bash /any/path/rebuild.sh     (absolute path)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/config.env"
NS=frc-scheduler-server

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: $CONFIG not found. Copy config.env.example and fill in your values."
  exit 1
fi

source "$CONFIG"

: "${APP_HOSTNAME:?Set APP_HOSTNAME in config.env}"
: "${GIT_REPO_URL:?Set GIT_REPO_URL in config.env}"
: "${CERT_ISSUER:?Set CERT_ISSUER in config.env}"

METALLB_IP="${METALLB_IP:-}"

# Shared substitution function — same as apply.sh
apply_manifest() {
  local file="$1"
  sed \
    -e "s|YOUR_HOSTNAME|${APP_HOSTNAME}|g" \
    -e "s|https://YOUR_HOSTNAME|https://${APP_HOSTNAME}|g" \
    -e "s|https://github.com/YOUR_ORG/YOUR_REPO.git|${GIT_REPO_URL}|g" \
    -e "s|letsencrypt-prod|${CERT_ISSUER}|g" \
    -e "s|METALLB_IP|${METALLB_IP}|g" \
    "$file" | oc apply -f -
}

# Helper: refresh image registry credentials (NooBaa S3)
refresh_registry() {
  echo "    Refreshing image registry operator (NooBaa credential reconcile)..."
  oc patch configs.imageregistry.operator.openshift.io cluster \
    --type merge --patch '{"spec":{"managementState":"Removed"}}' 2>/dev/null || true
  sleep 15
  oc patch configs.imageregistry.operator.openshift.io cluster \
    --type merge --patch '{"spec":{"managementState":"Managed"}}' 2>/dev/null || true

  echo "    Waiting for registry deployment to be available..."
  for i in $(seq 1 24); do
    if oc get deployment image-registry -n openshift-image-registry \
        > /dev/null 2>&1; then
      break
    fi
    echo "    attempt $i/24 — waiting 5s for registry deployment..."
    sleep 5
  done

  echo "    Waiting for registry rollout..."
  oc rollout status deployment/image-registry \
    -n openshift-image-registry --timeout=120s 2>/dev/null || \
  oc rollout status deployment/image-registry \
    -n openshift-image-registry --timeout=120s 2>/dev/null || true
  echo "    Registry ready."
}

# Helper: wait for a build to complete (success or failure)
wait_for_build() {
  local BUILD="$1"
  echo "    Waiting for build $BUILD to complete..."
  while true; do
    PHASE=$(oc get build "$BUILD" -n "$NS" \
      -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    case "$PHASE" in
      Complete)
        echo "    Build $BUILD completed successfully."
        return 0
        ;;
      Failed|Error|Cancelled)
        echo "    Build $BUILD failed (phase: $PHASE)."
        echo "    Logs:"
        oc logs "build/$BUILD" -n "$NS" --tail=40 2>/dev/null || true
        return 1
        ;;
      *)
        echo "    Build phase: $PHASE — waiting 10s..."
        sleep 10
        ;;
    esac
  done
}

# ── 1. Tear down everything ───────────────────────────────────────────────────
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

echo ""
echo "==> Remaining resources (should be empty):"
oc get all -n "$NS" 2>/dev/null || echo "  (none)"

# ── 2. Refresh registry AFTER teardown ───────────────────────────────────────
echo ""
echo "==> [pre-build] Refreshing image registry credentials..."
refresh_registry

# ── 3. Secrets ────────────────────────────────────────────────────────────────
echo ""
echo "==> [1/6] Applying secrets..."
oc apply -f "$SCRIPT_DIR/01-secrets.yaml"

# ── 4. Postgres ───────────────────────────────────────────────────────────────
echo ""
echo "==> [2/6] Deploying Postgres..."
<<<<<<< HEAD
oc apply -f "$SCRIPT_DIR/02-postgres.yaml"
=======
apply_manifest "$SCRIPT_DIR/02-postgres.yaml"
>>>>>>> 1df6f67 (Use the correct namespace and use a subdirectory in the postgres pvc. Allow build pods network access. Ensure rebuild.sh uses config.env)
oc rollout status deployment/frc-postgres -n "$NS" --timeout=120s

# ── 5. Build ──────────────────────────────────────────────────────────────────
echo ""
echo "==> [3/6] Applying BuildConfig..."
<<<<<<< HEAD
oc apply -f "$SCRIPT_DIR/03-buildconfig.yaml"
=======
apply_manifest "$SCRIPT_DIR/03-buildconfig.yaml"
>>>>>>> 1df6f67 (Use the correct namespace and use a subdirectory in the postgres pvc. Allow build pods network access. Ensure rebuild.sh uses config.env)

echo "    Waiting for builder service account registry secret..."
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
echo "    Live logs (Ctrl-C safe — status polling continues):"
oc logs -f "build/$BUILD_NAME" -n "$NS" 2>/dev/null || true
echo ""
wait_for_build "$BUILD_NAME"

# ── 6. Deploy app ─────────────────────────────────────────────────────────────
echo ""
echo "==> [4/6] Deploying application..."
<<<<<<< HEAD
oc apply -f "$SCRIPT_DIR/04-deployment.yaml"
=======
apply_manifest "$SCRIPT_DIR/04-deployment.yaml"
>>>>>>> 1df6f67 (Use the correct namespace and use a subdirectory in the postgres pvc. Allow build pods network access. Ensure rebuild.sh uses config.env)
oc rollout status deployment/frc-scheduler-server -n "$NS" --timeout=300s

# ── 7. Route ──────────────────────────────────────────────────────────────────
echo ""
echo "==> [5/6] Applying route..."
<<<<<<< HEAD
oc apply -f "$SCRIPT_DIR/05-route.yaml"
=======
apply_manifest "$SCRIPT_DIR/05-route.yaml"
>>>>>>> 1df6f67 (Use the correct namespace and use a subdirectory in the postgres pvc. Allow build pods network access. Ensure rebuild.sh uses config.env)

# ── 8. CronJob + RBAC ─────────────────────────────────────────────────────────
echo ""
echo "==> [6/6] Applying build CronJob and RBAC..."
<<<<<<< HEAD
oc apply -f "$SCRIPT_DIR/07-build-trigger-sa.yaml"
oc apply -f "$SCRIPT_DIR/08-build-cronjob.yaml"
=======
apply_manifest "$SCRIPT_DIR/07-build-trigger-sa.yaml"
apply_manifest "$SCRIPT_DIR/08-build-cronjob.yaml"
>>>>>>> 1df6f67 (Use the correct namespace and use a subdirectory in the postgres pvc. Allow build pods network access. Ensure rebuild.sh uses config.env)

# ── 9. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "==> Rebuild complete. Current state:"
oc get pods    -n "$NS"
oc get cronjob -n "$NS"
echo ""
HOST=$(oc get route frc-scheduler-server -n "$NS" \
  -o jsonpath='{.spec.host}' 2>/dev/null || echo "(route not yet ready)")
echo "App URL: https://$HOST"
