#!/bin/sh
# Apply all OpenShift manifests with site-specific values substituted.
# Usage: ./openshift/apply.sh
#
# Prerequisites:
#   - oc logged in to your cluster
#   - openshift/config.env filled in (or config.env.local for gitignored values)
#   - cert-manager operator installed with a ClusterIssuer ready

set -e
cd "$(dirname "$0")"

# Load config — prefer config.env.local (gitignored) over config.env
if [ -f config.env.local ]; then
  . ./config.env.local
  echo "Using config.env.local"
elif [ -f config.env ]; then
  . ./config.env
  echo "Using config.env"
else
  echo "ERROR: config.env not found. Copy config.env.example to config.env and fill in your values." >&2
  exit 1
fi

# Validate required values
for var in GIT_REPO_URL APP_HOSTNAME CERT_ISSUER; do
  eval val=\$$var
  if [ -z "$val" ] || echo "$val" | grep -q "YOUR_"; then
    echo "ERROR: $var is not set in config.env" >&2
    exit 1
  fi
done

# Substitute placeholders and pipe to oc apply
substitute() {
  sed \
    -e "s|https://github.com/YOUR_ORG/YOUR_REPO.git|${GIT_REPO_URL}|g" \
    -e "s|github.com/YOUR_ORG/YOUR_REPO.git|$(echo "$GIT_REPO_URL" | sed 's|https://||')|g" \
    -e "s|YOUR_HOSTNAME|${APP_HOSTNAME}|g" \
    -e "s|https://YOUR_HOSTNAME|https://${APP_HOSTNAME}|g" \
    -e "s|letsencrypt-prod|${CERT_ISSUER}|g" \
    -e "s|metallb.universe.tf/loadBalancerIPs: \"\"|metallb.universe.tf/loadBalancerIPs: \"${METALLB_IP}\"|g" \
    "$1"
}

echo ""
echo "Applying manifests for: ${APP_HOSTNAME}"
echo ""

# NOTE: 01-secrets.yaml is NOT applied here — create secrets manually first:
#   cp openshift/01-secrets.yaml.example openshift/01-secrets.yaml
#   edit openshift/01-secrets.yaml with real values
#   oc apply -f openshift/01-secrets.yaml
#   rm openshift/01-secrets.yaml  (never commit real secrets)
for manifest in \
  00-namespace.yaml \
  02-postgres.yaml \
  03-buildconfig.yaml \
  04-deployment.yaml \
  05-route.yaml \
  07-build-trigger-sa.yaml \
  08-build-cronjob.yaml \
  09-certificate.yaml \
  10-networkpolicy.yaml; do

  if [ -f "$manifest" ]; then
    echo "→ $manifest"
    substitute "$manifest" | oc apply -f -
  fi
done

echo ""
echo "Done. Check cert status with:"
echo "  oc get certificate frc-scheduler-tls -n frc-scheduler-server -w"
