-- Administrator bootstrap only. The inference job never references this integration.
USE ROLE ACCOUNTADMIN;
CREATE OR REPLACE NETWORK RULE MYUVIE_DB.APP.MODEL_DOWNLOAD_RULE
  MODE = EGRESS TYPE = HOST_PORT
  VALUE_LIST = (
    'huggingface.co',
    '*.huggingface.co',
    '*.hf.co',
    'cdn-lfs-us-1.hf.co',
    'drive.usercontent.google.com',
    'download.pytorch.org'
  );
CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS MYUVIE_MODEL_DOWNLOAD_EAI
  ALLOWED_NETWORK_RULES = (MYUVIE_DB.APP.MODEL_DOWNLOAD_RULE)
  ENABLED = TRUE;
GRANT USAGE ON INTEGRATION MYUVIE_MODEL_DOWNLOAD_EAI TO ROLE MYUVIE_DEV;
