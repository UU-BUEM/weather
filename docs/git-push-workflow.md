# Git Push Automation Workflow

## Recommended Standard

Use this layered approach:

1. Keep reusable automation in scripts:
   - push.sh for Bash users
   - push.ps1 for PowerShell users
2. Keep local, user-specific message content in a local file:
   - .commit-message.md (ignored)
3. Keep release/change narrative in CHANGELOG.md:
   - scripts can derive commit message/body from [Unreleased]

This keeps scripts generic and your day-to-day commit text customizable.

## File Locations

- Repository root:
  - push.sh (local helper, ignored)
  - push.ps1 (local helper, ignored)
  - .commit-message.md (local message source, ignored)
- Tracked project docs:
  - docs/git-push-workflow.md
  - CHANGELOG.md

If you want team-shared automation later, move the scripts into scripts/git/ and remove them from .gitignore.

## Message Source Priority

Both scripts use this priority:

1. Explicit message argument
2. Message file (.commit-message.md)
3. Changelog [Unreleased] section (only when requested)

## Usage

### Bash

- Explicit message:
  - ./push.sh -m "fix: handle missing provider"
- From message file:
  - ./push.sh -f .commit-message.md
- From changelog:
  - ./push.sh -c
- With tag:
  - ./push.sh -m "release: v1.0.1" -t v1.0.1 --tag-message "v1.0.1"

### PowerShell

- Explicit message:
  - .\push.ps1 -Message "fix: handle missing provider"
- From message file:
  - .\push.ps1 -MessageFile .commit-message.md
- From changelog:
  - .\push.ps1 -FromChangelog
- With tag:
  - .\push.ps1 -Message "release: v1.0.1" -Tag v1.0.1 -TagMessage "v1.0.1"

## Notes

- Scripts stage all changes via git add -A.
- If there are no staged changes, scripts exit without committing.
- Validate CHANGELOG.md before using changelog-derived commit messages.
