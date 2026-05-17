"""
config.py — Environment configuration for Ariba/Coupa PO Automation Agent.
Env vars injected by Azure Container App (Bicep) or .env file locally.
Pydantic Settings handles UPPER_SNAKE → lower_snake mapping automatically.
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──
    app_name: str = "Ariba/Coupa PO Automation Agent"
    app_version: str = "1.1.0"
    environment: str = "development"
    debug: bool = False
    port: int = 8000

    # ── Azure SQL Staging DB ──
    staging_sql_server: str = ""
    staging_sql_database: str = "po_staging"
    staging_sql_driver: str = "{ODBC Driver 18 for SQL Server}"

    # ── Azure Blob Storage ──
    # Bicep injects: BLOB_ACCOUNT_URL, BLOB_CONTAINER, BLOB_CONNECTION_STRING
    blob_account_url: str = ""
    blob_container: str = "ariba-coupa"
    blob_connection_string: str = ""

    # ── Azure Document Intelligence (PDF parsing) ──
    # Bicep injects: DOC_INTEL_ENDPOINT, DOC_INTEL_KEY
    doc_intel_endpoint: str = ""
    doc_intel_key: str = ""

    # ── Azure OpenAI (optional — for AI-assisted field mapping) ──
    # Bicep injects: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, AZURE_OPENAI_MODEL
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_model: str = "gpt-4.1"

    # ── Microsoft Graph API (email polling) ──
    graph_client_id: str = ""
    graph_client_secret: str = ""
    graph_tenant_id: str = ""
    graph_mailbox: str = "orders@enproinc.com"
    graph_poll_interval: int = 60

    # Aliases for Azure AD credentials (used by email_poller)
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # ── Dynamics 365 CRM ──
    dynamics_org_url: str = ""
    dynamics_client_id: str = ""
    dynamics_client_secret: str = ""
    dynamics_tenant_id: str = ""

    # ── P21 SQL (direct ODBC for SO pull / reads) ──
    p21_sql_server: str = ""
    p21_sql_database: str = "P21"
    p21_sql_driver: str = "{ODBC Driver 17 for SQL Server}"
    p21_sql_uid: str = ""
    p21_sql_pwd: str = ""
    p21_company_no: int = 1
    p21_location_id: int = 10

    # ── P21 Transaction API (SO creation via REST) ──
    # Middleware must be installed on the P21 server
    p21_base_url: str = ""  # e.g. https://192.168.1.100:3333
    p21_api_username: str = ""
    p21_api_password: str = ""
    p21_verify_ssl: bool = False
    p21_default_taker: str = "POAGENT"
    p21_default_company_id: str = "1"
    p21_default_location_id: str = "10"
    p21_auto_submit_on_approve: bool = False  # Set to true to auto-submit approved POs to P21 API

    # ── Persistent Storage ──
    # Azure Files mount at /app/data (Container App) or Render disk
    # Bicep injects: CROSSWALK_DIR, CISM_OUTPUT_DIR, CISM_SO_OUTPUT_DIR
    cism_output_dir: str = "/app/data/cism_output"
    cism_so_output_dir: str = "/app/data/cism_so_output"
    crosswalk_dir: str = "/app/data/crosswalks"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
