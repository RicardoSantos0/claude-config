#!/usr/bin/env bash
# Links ~/.claude/agents, ~/.claude/commands, and ~/.claude/skills to this repo.
# Run once per machine after cloning.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

link() {
  local target="$REPO_DIR/$1"
  local link="$CLAUDE_DIR/$1"

  if [ -L "$link" ]; then
    echo "Already linked: $link"
  elif [ -d "$link" ]; then
    echo "Backing up existing $link -> ${link}.bak"
    mv "$link" "${link}.bak"
    ln -s "$target" "$link"
    echo "Linked: $link -> $target"
  else
    ln -s "$target" "$link"
    echo "Linked: $link -> $target"
  fi
}

link agents
link commands
link skills
