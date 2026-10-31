# Store development

- This repository is public. New branches must start from the public `main` baseline.
- Earlier local worktrees may contain private deployment history. Do not push those refs, backups, or use `git push --all` / `--mirror`.
- Keep runtime data, private configuration, keys, real-device reports and screenshots outside Git. Only synthetic fixtures and generic configuration examples belong in public commits.
- Run `python3 scripts/check_public_files.py` and relevant tests before pushing. CI uses disposable test keys and local temporary repositories; it must not contact or modify a live deployment.
- Publishing source does not authorize restarting, redeploying or changing the running store, its repository signing identity, DNS records or client settings.
