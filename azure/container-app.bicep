@description('Location for all resources')
param location string = resourceGroup().location

@description('Container image tag')
param imageTag string = 'latest'

var containerAppName = 'enpro-po-agent'
var acrServer = 'enprofm20260328.azurecr.io'
var imageName = '${acrServer}/enpro-po-agent:${imageTag}'
var environmentId = resourceId('Microsoft.App/managedEnvironments', 'cae-enpro-fm')
var keyVaultName = 'kv-enpro-fm'
var storageAccountName = 'enproaidatav1'
var fileShareName = 'po-agent-data'
var storageMountName = 'po-agent-data-mount'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acrServer
          identity: 'system'
        }
      ]
      secrets: [
        {
          name: 'blob-connection-string'
          keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/secrets/blob-connection-string'
          identity: 'system'
        }
        {
          name: 'doc-intel-key'
          keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/secrets/doc-intel-key'
          identity: 'system'
        }
        {
          name: 'azure-openai-key'
          keyVaultUrl: 'https://${keyVaultName}.vault.azure.net/secrets/azure-openai-key'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: containerAppName
          image: imageName
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'PORT', value: '8000' }
            { name: 'ENVIRONMENT', value: 'production' }
            { name: 'BLOB_ACCOUNT_URL', value: 'https://enproaidatav1.blob.core.windows.net' }
            { name: 'BLOB_CONTAINER', value: 'ariba-coupa' }
            { name: 'BLOB_CONNECTION_STRING', secretRef: 'blob-connection-string' }
            { name: 'DOC_INTEL_ENDPOINT', value: 'https://enpro-filtration-ai.cognitiveservices.azure.com/' }
            { name: 'DOC_INTEL_KEY', secretRef: 'doc-intel-key' }
            { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://enpro-filtration-ai.cognitiveservices.azure.com/' }
            { name: 'AZURE_OPENAI_KEY', secretRef: 'azure-openai-key' }
            { name: 'AZURE_OPENAI_MODEL', value: 'gpt-4.1' }
            { name: 'CROSSWALK_DIR', value: '/app/data/crosswalks' }
            { name: 'CISM_OUTPUT_DIR', value: '/app/data/cism_output' }
            { name: 'CISM_SO_OUTPUT_DIR', value: '/app/data/cism_so_output' }
          ]
          volumeMounts: [
            {
              volumeName: storageMountName
              mountPath: '/app/data'
            }
          ]
        }
      ]
      volumes: [
        {
          name: storageMountName
          storageType: 'AzureFile'
          storageName: storageMountName
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output systemAssignedIdentityId string = containerApp.identity.principalId
