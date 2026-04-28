#!/bin/bash
# Apply all OpenShift manifests with config substitution.
# Can be run from anywhere:
#   ./openshift/apply.sh   (from repo root)
#   ./apply.sh             (from inside openshift/)
set -e

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

# Verify DATABASE_URL is in the secret before applying anything
if oc get secret frc-db-secret -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "Verifying DATABASE_URL in frc-db-secret..."
  check_db_secret "$NAMESPACE" || true
fi

echo "Applying manifests to namespace: ${NAMESPACE}"
for manifest in "$SCRIPT_DIR"/[0-9]*.yaml; do
  echo "  -> $(basename "$manifest")"
  apply_manifest "$manifest"
  # After applying postgres, wait for the database to be ready
  if [[ "$(basename "$manifest")" == "02-postgres.yaml" ]]; then
    oc rollout status deployment/frc-postgres -n "$NAMESPACE" --timeout=120s
    PG_USER=$(oc get secret frc-db-secret -n "$NAMESPACE" \
      -o jsonpath='{.data.POSTGRES_USER}' | base64 -d)
    PG_DB=$(oc get secret frc-db-secret -n "$NAMESPACE" \
      -o jsonpath='{.data.POSTGRES_DB}' | base64 -d)
    wait_for_postgres_db "$NAMESPACE" "$PG_USER" "$PG_DB"
  fi
done

# Restart the app deployment so pods pick up any secret changes.
# Kubernetes does not automatically restart pods when secrets change.
if oc get deployment frc-scheduler-server -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "  Restarting app deployment to pick up latest secrets..."
  oc rollout restart deployment/frc-scheduler-server -n "$NAMESPACE"
fi

# If --build flag passed, refresh registry credentials and trigger a build.
if [[ "${1:-}" == "--build" ]]; then
  echo ""
  echo "==> Triggering build..."
  refresh_registry
  refresh_builder_credentials "$NAMESPACE"
  oc start-build frc-scheduler-server-git -n "$NAMESPACE" --follow
else
  echo ""
  echo "Done."
  echo "To trigger a build: oc start-build frc-scheduler-server-git --follow -n ${NAMESPACE}"
  echo "Or run:             ./apply.sh --build"
fi
