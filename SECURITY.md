# Security and publication boundary

The upload API trusts holders of its API key to publish applications. It is intended for a trusted host or private network, with a separate public, read-only download service. It does not provide user accounts or tenant isolation.

- Keep API keys, repository signing keys, DNS tokens, TLS state, SSH identities and runtime configuration outside version control. Checked-in files contain placeholders or loopback defaults.
- APK signatures must remain consistent and version codes must increase. Repository signing and application signing use separate identities.
- Only expose the download service publicly. Upload authentication checks the direct network peer and the API key; forwarded headers do not grant access.
- Tests generate disposable keys with explicitly public test passwords. Never use those keys or passwords for a real deployment.
- The Android scripts require privileged installation and a prepared chroot. Keep an independent recovery channel when changing SSH or boot services.

The public history starts from a sanitized source snapshot. Earlier local history, operational validation notes, personal app metadata and deployment records are not published. Secret scanning does not prove the absence of every possible sensitive value; reviewers must also check addresses, device identifiers, configuration and attachments.

Use `python3 scripts/check_public_files.py` to check the tracked public file set. Do not attach production credentials, logs or real-device screenshots to public issues. No dedicated private vulnerability reporting address is configured.
