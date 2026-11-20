#!/usr/bin/env just --justfile
set shell := ["zsh", "-cu"]
set fallback

default:
  just -u --list

test:
  uv run pytest -q

dev:
  uv run mcp dev src/postgres_mcp/server.py

release-help:
  @echo "- bump version in pyproject.toml"
  @echo "- uv lock && uv sync"
  @echo "- commit and push to main"
  @echo "- git tag vX.Y.Z && git push origin vX.Y.Z"
  @echo "  (Release workflow: PyPI + GitHub Release + ghcr.io/poiig/postgresql-mcp-pro)"

release version note: # version without v prefix
  #!/usr/bin/env bash
  if [[ "{{version}}" == v* ]]; then
    echo "Error: Do not include 'v' prefix in version."
    exit 1
  fi
  git tag -a "v{{version}}" -m "{{note}}"
  git push origin "v{{version}}"
