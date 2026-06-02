#!/bin/bash
set -e

RG="rg-enpro-ai"
ACR="enprofm20260328"
APP="enpro-po-agent"
IMAGE="enpro/po-agent"
TAG="v1.0-azure"
ENV_NAME="cae-enpro-fm"
PORT=8000

ENV_VARS=(
  "PORT=$PORT"
  "ENVIRONMENT=production"
  "BLOB_ACCOUNT_URL=https://enproaidatav1.blob.core.windows.net"
  "BLOB_CONTAINER=ariba-coupa"
  "DOC_INTEL_ENDPOINT=https://enpro-filtration-ai.cognitiveservices.azure.com/"
  "AZURE_OPENAI_ENDPOINT=https://enpro-filtration-ai.cognitiveservices.azure.com/"
  "AZURE_OPENAI_MODEL=gpt-4.1"
  "CROSSWALK_DIR=/app/data/crosswalks"
  "CISM_OUTPUT_DIR=/app/data/cism_output"
  "CISM_SO_OUTPUT_DIR=/app/data/cism_so_output"
)

echo "=== Enpro PO Agent — Azure Deploy ==="
echo "Registry: $ACR | App: $APP | Image: $IMAGE:$TAG"
echo ""

echo "--- Building image in ACR ---"
az acr build --registry $ACR --image $IMAGE:$TAG . --no-logs

if [ "$1" == "--create" ]; then
  echo ""
  echo "--- Creating Container App (first-time) ---"
  az containerapp create \
    --name $APP \
    --resource-group $RG \
    --environment $ENV_NAME \
    --registry-server $ACR.azurecr.io \
    --image $ACR.azurecr.io/$IMAGE:$TAG \
    --cpu 0.5 --memory 1Gi \
    --min-replicas 0 --max-replicas 3 \
    --ingress external --target-port $PORT \
    --env-vars "${ENV_VARS[@]}"
else
  echo ""
  echo "--- Updating existing Container App ---"
  az containerapp update \
    --name $APP \
    --resource-group $RG \
    --image $ACR.azurecr.io/$IMAGE:$TAG \
    --cpu 0.5 --memory 1Gi \
    --min-replicas 0 --max-replicas 3

  az containerapp update \
    --name $APP \
    --resource-group $RG \
    --set-env-vars "${ENV_VARS[@]}"
fi

echo ""
echo "=== Deploy complete ==="

FQDN=$(az containerapp show --name $APP --resource-group $RG --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null)
if [ -n "$FQDN" ]; then
  echo "URL: https://$FQDN"
else
  echo "URL: check Azure portal for FQDN"
fi

echo ""
echo "--- REMINDER: Set secrets manually ---"
echo "az containerapp update --name $APP --resource-group $RG --set-env-vars \\"
echo "  BLOB_CONNECTION_STRING=secretref:blob-conn-string \\"
echo "  DOC_INTEL_KEY=secretref:doc-intel-key \\"
echo "  AZURE_OPENAI_KEY=secretref:azure-openai-key"
echo ""
echo "Or set as Container App secrets first:"
echo "az containerapp secret set --name $APP --resource-group $RG --secrets \\"
echo "  blob-conn-string=\"<value>\" \\"
echo "  doc-intel-key=\"<value>\" \\"
echo "  azure-openai-key=\"<value>\""
