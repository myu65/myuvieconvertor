-- Hardened GitHub Environment subject established for this repository.
USE ROLE USERADMIN;
CREATE USER IF NOT EXISTS MYUVIE_GITHUB
  TYPE = SERVICE
  DEFAULT_ROLE = MYUVIE_DEV
  DEFAULT_NAMESPACE = 'MYUVIE_DB.APP'
  WORKLOAD_IDENTITY = (
    TYPE = OIDC
    ISSUER = 'https://token.actions.githubusercontent.com'
    SUBJECT = 'repo:myu65@11177688/myuvieconvertor@1319240654:environment:snowflake-dev'
  );
GRANT ROLE MYUVIE_DEV TO USER MYUVIE_GITHUB;
