#!/bin/bash
# setup_azure_storage.sh
# One-time provisioning of Azure Files share for the PO Agent Container App.
# Run this ONCE before deploying the Container App.
#
# Prerequisites:
#   - az CLI installed and logged in
#   - Storage account 'enproaidatav1' already exists in rg-enpro-ai
#   - Container Apps Environment 'cae-enpro-fm' already exists in rg-enpro-ai

set -euo pipefail

RESOURCE_GROUP="rg-enpro-ai"
STORAGE_ACCOUNT="enproaidatav1"
SHARE_NAME="po-agent-data"
ENVIRONMENT="cae-enpro-fm"
STORAGE_MOUNT_NAME="poagentdata"

echo "=== Step 1: Create Azure Files share '${SHARE_NAME}' ==="
az storage share-rm create \
  --resource-group "$RESOURCE_GROUP" \
  --storage-account "$STORAGE_ACCOUNT" \
  --name "$SHARE_NAME" \
  --quota 5 \
  --output table

echo ""
echo "=== Step 2: Get storage account key ==="
STORAGE_KEY=$(az storage account keys list \
  --resource-group "$RESOURCE_GROUP" \
  --account-name "$STORAGE_ACCOUNT" \
  --query "[0].value" \
  --output tsv)
echo "Storage key retrieved (not printed for security)."

echo ""
echo "=== Step 3: Create storage mount in Container Apps Environment ==="
# This links the Azure Files share to the environment so Container Apps can reference it.
az containerapp env storage set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ENVIRONMENT" \
  --storage-name "$STORAGE_MOUNT_NAME" \
  --azure-file-account-name "$STORAGE_ACCOUNT" \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name "$SHARE_NAME" \
  --access-mode ReadWrite \
  --output table

echo ""
echo "=== Step 4: Create directory structure in file share ==="
# Pre-create the directories the app expects at /mnt/data/
DIRS=(
  "crosswalks"
  "cism_output"
  "cism_so_output"
  "po_store"
  "p21_data"
  "quote_data"
  "logs"
)

for dir in "${DIRS[@]}"; do
  az storage directory create \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --share-name "$SHARE_NAME" \
    --name "$dir" \
    --output none
  echo "  Created: ${dir}/"
done

echo ""
echo "=== Setup complete ==="
echo ""
echo "When creating the Container App, wire the volume mount like this:"
echo ""
echo "  az containerapp create \\"
echo "    --name ca-enpro-po-agent \\"
echo "    --resource-group ${RESOURCE_GROUP} \\"
echo "    --environment ${ENVIRONMENT} \\"
echo "    --image <your-acr>.azurecr.io/po-agent:latest \\"
echo "    --target-port 8000 \\"
echo "    --ingress external \\"
echo "    --min-replicas 0 \\"
echo "    --max-replicas 1 \\"
echo "    --secret storage-key=\"${STORAGE_KEY}\" \\"
echo "    --env-vars AZURE_STORAGE_KEY=secretref:storage-key \\"
echo "    --yaml containerapp.yaml"
echo ""
echo "In your containerapp.yaml, include the volume + volumeMount:"
echo ""
echo "  template:"
echo "    volumes:"
echo "      - name: poagentdata"
echo "        storageName: ${STORAGE_MOUNT_NAME}"
echo "        storageType: AzureFile"
echo "    containers:"
echo "      - name: po-agent"
echo "        volumeMounts:"
echo "          - volumeName: poagentdata"
echo "            mountPath: /app/data"
echo ""
echo "Storage key (save this for Container App secrets):"
echo "  ${STORAGE_KEY}"
