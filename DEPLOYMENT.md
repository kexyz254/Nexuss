# Nexuss P0 Deployment

**CONFIDENTIAL — NEXUSS AI — kexyz254peter**

This repository contains Prototype Increment P0: the Nexuss AI OS engineering foundation.

## Safe deployment

Use `scripts/deploy_to_github.ps1` from Windows PowerShell. The script clones the target repository, copies this foundation without deleting unrelated existing files, validates the repository, runs available tests, creates a commit, and pushes to `main`.

## Post-deployment controls

1. Confirm the repository is private.
2. Enable branch protection for `main`.
3. Require pull-request review and passing CI.
4. Enable secret scanning and dependency alerts.
5. Restrict repository access to approved contributors.
6. Do not add production credentials or ATS strategy internals.
