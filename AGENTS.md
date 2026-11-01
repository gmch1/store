# Store development

- This repository is public. New branches must start from the public `main` baseline.
- Earlier local worktrees may contain private deployment history. Do not push those refs, backups, or use `git push --all` / `--mirror`.
- Keep runtime data, private configuration, keys, real-device reports and screenshots outside Git. Only synthetic fixtures and generic configuration examples belong in public commits.
- Run `python3 scripts/check_public_files.py` and relevant tests before pushing. CI uses disposable test keys and local temporary repositories; it must not contact or modify a live deployment.
- Publishing source does not authorize restarting, redeploying or changing the running store, its repository signing identity, DNS records or client settings.

# Client maintenance

- The canonical client build is `python3 scripts/build_client.py`; use `.env.client` or `STORE_CLIENT_*` environment variables for deployment-specific values. Only `.env.client.example` belongs in Git.
- Keep the upstream pin in `client/upstream.json`, our generic Android changes in `client/patches/series.json`, and package/version metadata in `client/release.json`. Do not put deployment literals into patches.
- APK keys and password files remain outside Git and outside source archives. Reuse the existing identity; builds verify `STORE_CLIENT_CERTIFICATE_SHA256` and must not create replacement keys.
- CI uses `--example-config --unsigned`. Store real-device evidence under `.local/`, never in public commits. See `docs/project-layout.md` for ownership and publication boundaries.
