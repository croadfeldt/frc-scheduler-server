# common.sh — shared functions for apply.sh and rebuild.sh
# Sourced by both scripts, not executed directly.

apply_manifest() {
  local file="$1"
  sed \
    -e "s|NAMESPACE_PLACEHOLDER|${NAMESPACE}|g" \
    -e "s|YOUR_HOSTNAME|${APP_HOSTNAME}|g" \
    -e "s|https://YOUR_HOSTNAME|https://${APP_HOSTNAME}|g" \
    -e "s|https://github.com/YOUR_ORG/YOUR_REPO.git|${GIT_REPO_URL}|g" \
    -e "s|GIT_BRANCH_PLACEHOLDER|${GIT_BRANCH}|g" \
    -e "s|letsencrypt-prod|${CERT_ISSUER}|g" \
    -e "s|METALLB_IP_PLACEHOLDER|${METALLB_IP}|g" \
    -e "s|K8S_SERVICE_CIDR_PLACEHOLDER|${K8S_SERVICE_CIDR}|g" \
    -e "s|APP_PORT_PLACEHOLDER|${APP_PORT}|g" \
    -e "s|CPU_WORKERS_PLACEHOLDER|${CPU_WORKERS}|g" \
    -e "s|WEB_WORKERS_PLACEHOLDER|${WEB_WORKERS}|g" \
    "$file" | oc apply -f -
}

# Wait for the POSTGRES_DB database to accept queries.
# pg_isready returns true as soon as postgres accepts connections — before
# initdb has finished creating POSTGRES_DB. This checks the actual database.
wait_for_postgres_db() {
  local pg_user="$1"
  local pg_db="$2"
  echo "    Waiting for database '$pg_db' to be ready..."
  for i in $(seq 1 36); do
    if oc exec -n "$NAMESPACE" deployment/frc-postgres -- \
        psql -U "$pg_user" -d "$pg_db" -c "SELECT 1" -q --no-align -t \
        > /dev/null 2>&1; then
      echo "    Database '$pg_db' is ready."
      return 0
    fi
    echo "    attempt $i/36 — waiting 5s..."
    sleep 5
  done
  echo "ERROR: Database '$pg_db' did not become ready after 3 minutes."
  oc logs -n "$NAMESPACE" deployment/frc-postgres --tail=30 2>/dev/null || true
  return 1
}
