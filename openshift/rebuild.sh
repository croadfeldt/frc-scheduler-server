#!/usr/bin/env bash
# openshift/rebuild.sh — Full teardown and rebuild of the frc-scheduler-server namespace.
# Usage: bash openshift/rebuild.sh
# Run from the repo root directory.

set -euo pipefail

NS=frc-scheduler-server

echo "==> Tearing down all resources in namespace: $NS"
oc delete all        --all -n "$NS" --ignore-not-found
oc delete pvc        --all -n "$NS" --ignore-not-found
oc delete secret     --all -n "$NS" --ignore-not-found
oc delete configmap  --all -n "$NS" --ignore-not-found
oc delete sa         --all -n "$NS" --ignore-not-found
oc delete rolebinding --all -n "$NS" --ignore-not-found
oc delete role       --all -n "$NS" --ignore-not-found

echo ""
echo "==> Waiting for all pods to terminate..."
oc wait --for=delete pod --all -n "$NS" --timeout=60s 2>/dev/null || true

echo ""
echo "==> Remaining resources (should be empty):"
oc get all -n "$NS" 2>/dev/null || echo "  (none)"

echo ""
echo "==> [1/6] Applying secrets..."
oc apply -f openshift/01-secrets.yaml

echo ""
echo "==> [2/6] Deploying Postgres..."
oc apply -f openshift/02-postgres.yaml
oc rollout status deployment/frc-postgres -n "$NS" --timeout=120s

echo ""
echo "==> [3/6] Applying BuildConfig and starting build..."
oc apply -f openshift/03-buildconfig.yaml
oc start-build frc-scheduler-server-git --follow -n "$NS"

echo ""
echo "==> [4/6] Deploying application..."
oc apply -f openshift/04-deployment.yaml
oc rollout status deployment/frc-scheduler-server -n "$NS" --timeout=120s

echo ""
echo "==> [5/6] Applying route (120s timeout)..."
oc apply -f openshift/05-route.yaml

echo ""
echo "==> [6/6] Applying build CronJob and RBAC..."
oc apply -f openshift/07-build-trigger-sa.yaml
oc apply -f openshift/08-build-cronjob.yaml

echo ""
echo "==> Rebuild complete. Current state:"
oc get pods      -n "$NS"
oc get cronjob   -n "$NS"
echo ""
HOST=$(oc get route frc-scheduler-server -n "$NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "(route not yet ready)")
echo "App URL: https://$HOST"
