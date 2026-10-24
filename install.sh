#!/usr/bin/env bash
# Installs the research scripts and skills into ~/.claude. Never overwrites existing files.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
dest="${HOME}/.claude"

mkdir -p "$dest/research-kit" "$dest/skills"
for f in citation_check.py; do
  cp -n "$here/scripts/$f" "$dest/research-kit/$f" || true
done

for s in citation-check; do
  if [ -e "$dest/skills/$s" ]; then
    echo "skip: $dest/skills/$s already exists"
  else
    cp -R "$here/skills/$s" "$dest/skills/$s"
    echo "installed skill: $s"
  fi
done

echo "Done. Try: python3 ~/.claude/research-kit/citation_check.py examples/ai-music-refs.bib, or ask Claude Code to "check my citations"."
