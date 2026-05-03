#!/bin/bash
# openshift/apply.sh — Deploy/update FRC Match Scheduler.
#
# Usage:
#   ./apply.sh             # apply all manifests; restart deployment for secret changes
#   ./apply.sh --build     # apply manifests, build, and roll out the new image
#   ./apply.sh --rebuild   # full teardown + redeploy + build + rollout from scratch
#
# All modes wait for rollout completion and report the running pod + image
# on success. A failed rollout (>5min) exits non-zero.
#
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
METALLB_POOL="${METALLB_POOL:-server-vlan}"
APP_PORT="${APP_PORT:-8443}"
CPU_WORKERS="${CPU_WORKERS:-4}"
WEB_WORKERS="${WEB_WORKERS:-1}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-https://${APP_HOSTNAME}}"

NS="$NAMESPACE"
MODE="${1:-apply}"

# ── Mode: --rebuild (full teardown) ──────────────────────────────────────────
if [[ "$MODE" == "--rebuild" ]]; then
  echo "==> [rebuild] Tearing down all resources in namespace: $NS"
  oc delete all         --all -n "$NS" --ignore-not-found
  oc delete pvc         --all -n "$NS" --ignore-not-found
  oc delete secret      --all -n "$NS" --ignore-not-found
  oc delete configmap   --all -n "$NS" --ignore-not-found
  oc delete sa          --all -n "$NS" --ignore-not-found
  oc delete rolebinding --all -n "$NS" --ignore-not-found
  oc delete role        --all -n "$NS" --ignore-not-found
  oc wait --for=delete pod --all -n "$NS" --timeout=60s 2>/dev/null || true

  if [ ! -f "$SCRIPT_DIR/01-secrets.yaml" ]; then
    echo "ERROR: $SCRIPT_DIR/01-secrets.yaml not found."
    echo "Copy 01-secrets.yaml.example to 01-secrets.yaml and fill in your values."
    exit 1
  fi
  refresh_registry
fi

# ── DB secret check ──────────────────────────────────────────────────────────
if oc get secret frc-db-secret -n "$NAMESPACE" > /dev/null 2>&1; then
  echo "Verifying DATABASE_URL in frc-db-secret..."
  check_db_secret "$NAMESPACE" || true
fi

echo "Applying manifests to namespace: ${NAMESPACE}"

# Bootstrap: if the TLS secret doesn't exist yet, apply the Certificate first
# and wait for cert-manager to issue it. Otherwise the Deployment will
# crashloop because the tls-certs volume mount is mandatory.
if ! oc get secret frc-scheduler-tls -n "$NAMESPACE" >/dev/null 2>&1; then
  if [ -f "$SCRIPT_DIR/00-namespace.yaml" ]; then
    apply_manifest "$SCRIPT_DIR/00-namespace.yaml"
  fi
  if [ -f "$SCRIPT_DIR/06-certificate.yaml" ]; then
    echo "  -> bootstrap: applying 06-certificate.yaml first (no TLS secret yet)"
    apply_manifest "$SCRIPT_DIR/06-certificate.yaml"
    echo "    Waiting up to 5 min for cert-manager to issue frc-scheduler-tls..."
    for i in $(seq 1 60); do
      if oc get secret frc-scheduler-tls -n "$NAMESPACE" >/dev/null 2>&1; then
        echo "    Certificate issued."
        break
      fi
      sleep 5
    done
  fi
fi

# Clean up any orphaned cronjobs from previous deploys
for cj in $(oc get cronjob -n "$NAMESPACE" -o name 2>/dev/null \
            | grep -v "git-poll-trigger$" || true); do
  echo "  -> removing stale cronjob: $cj"
  oc delete "$cj" -n "$NAMESPACE" --ignore-not-found
done

for manifest in "$SCRIPT_DIR"/[0-9]*.yaml; do
  echo "  -> $(basename "$manifest")"
  # Skip certificate if already Ready — cert-manager manages renewal automatically
  if [[ "$(basename "$manifest")" == "06-certificate.yaml" ]]; then
    CERT_READY=$(oc get certificate frc-scheduler-tls -n "$NAMESPACE" \
      -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)
    if [[ "$CERT_READY" == "True" ]]; then
      echo "    Certificate already Ready — skipping (cert-manager manages renewal)"
    else
      apply_manifest "$manifest"
    fi
  else
    apply_manifest "$manifest"
  fi
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
# Skipped when --build/--rebuild is set since the build will trigger its own rollout.
if [[ "$MODE" != "--build" && "$MODE" != "--rebuild" ]]; then
  if oc get deployment frc-scheduler-server -n "$NAMESPACE" > /dev/null 2>&1; then
    echo "  Restarting app deployment to pick up latest secrets..."
    oc rollout restart deployment/frc-scheduler-server -n "$NAMESPACE"
    oc rollout status deployment/frc-scheduler-server -n "$NAMESPACE" --timeout=180s
  fi
fi

# If --build or --rebuild, refresh registry credentials, trigger a build,
# then explicitly roll out the new image and wait for the rollout to complete.
# OpenShift image-change triggers don't always pick up the new image reliably
# (especially on rebuilds where the image stream tag may resolve to the same
# digest temporarily), so we force a fresh rollout.
if [[ "$MODE" == "--build" || "$MODE" == "--rebuild" ]]; then
  echo ""
  echo "==> Triggering build..."
  refresh_registry
  refresh_builder_credentials "$NAMESPACE"
  oc start-build frc-scheduler-server-git -n "$NAMESPACE" --follow

  echo ""
  echo "==> Build complete — rolling out new image..."
  if oc get deployment frc-scheduler-server -n "$NAMESPACE" > /dev/null 2>&1; then
    oc rollout restart deployment/frc-scheduler-server -n "$NAMESPACE"
    if oc rollout status deployment/frc-scheduler-server -n "$NAMESPACE" --timeout=300s; then
      echo ""
      echo "==> Rollout complete. New pods are serving traffic."
      # Show the actual running pod and image for confirmation
      POD=$(oc get pod -n "$NAMESPACE" -l app=frc-scheduler-server \
            --field-selector=status.phase=Running \
            -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
      if [ -n "$POD" ]; then
        IMAGE=$(oc get pod "$POD" -n "$NAMESPACE" \
                -o jsonpath='{.spec.containers[0].image}' 2>/dev/null || true)
        echo "    Pod:   $POD"
        echo "    Image: $IMAGE"
      fi
    else
      echo ""
      echo "ERROR: Rollout did not complete within 5 minutes."
      echo "Check pod status with: oc get pods -n $NAMESPACE"
      echo "Check pod logs with:   oc logs -n $NAMESPACE -l app=frc-scheduler-server --tail=100"
      exit 1
    fi
  else
    echo "WARNING: Deployment frc-scheduler-server not found — skipping rollout."
  fi
else
  echo ""
  echo "Done."
  echo "To trigger a build:    ./apply.sh --build"
  echo "Full teardown+rebuild: ./apply.sh --rebuild"
fi
