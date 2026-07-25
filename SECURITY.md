# Security

## Local configuration

- Copy `backend/.env.example` to `backend/.env`.
- Keep all Supabase database URLs, service-role keys and Gemini keys on the
  backend only.
- Do not use secret values in `frontend/.env.local`, browser code, screenshots,
  logs or issue reports.
- `.gitignore` and `.dockerignore` exclude local environment files, but those
  controls do not remove secrets from existing Git history.

## If a credential was committed

1. Revoke or rotate it in Supabase, Google AI Studio or the relevant provider.
2. Update the local untracked `backend/.env` with the replacement.
3. Purge the secret-bearing file or value from every published Git ref with a
   reviewed history-rewrite procedure such as `git filter-repo`.
4. Force-push only after coordinating with every repository collaborator.
5. Invalidate old clones and CI caches, then verify with a secret scanner.

History rewriting and provider-side rotation are deliberately not automated by
the application because they affect collaborators and external accounts.

## Reporting

Report a suspected exposure privately to the repository owners. Do not include
the secret value in the report.
