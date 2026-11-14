#!/usr/bin/env bash
# Publish generated files to a dedicated branch without touching the working tree, the index,
# or any branch of the history being visualised.
#
# Usage: publish-artifact-branch.sh FILE [FILE...]
# Environment:
#   GITGRAPH_BRANCH   target branch (default: gitgraph-assets)
#   GITGRAPH_REMOTE   remote name   (default: origin)
#   GITGRAPH_MESSAGE  commit message (default: "Update & Share Graph")
#   GITGRAPH_DRY_RUN  if "true", create the commit locally but do not push
#
# The branch holds exactly the given files (by basename). The commit is built with plumbing
# (hash-object / mktree / commit-tree), parented on the current remote tip when one exists, so
# history of the artifact branch is preserved and nothing is force-pushed.
set -euo pipefail

branch="${GITGRAPH_BRANCH:-gitgraph-assets}"
remote="${GITGRAPH_REMOTE:-origin}"
message="${GITGRAPH_MESSAGE:-Update & Share Graph}"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 FILE [FILE...]" >&2
  exit 2
fi
case "$branch" in
  ""|-*|*..*|*" "*|*~*|*^*|*:*|*\\*) echo "error: unsafe branch name: $branch" >&2; exit 2 ;;
esac

entries=""
for file in "$@"; do
  [ -f "$file" ] || { echo "error: not a file: $file" >&2; exit 1; }
  name="$(basename -- "$file")"
  blob="$(git hash-object -w -- "$file")"
  entries="${entries}100644 blob ${blob}"$'\t'"${name}"$'\n'
done
tree="$(printf '%s' "$entries" | git mktree)"

parent=""
if git fetch --quiet --no-tags "$remote" "+refs/heads/${branch}:refs/remotes/${remote}/${branch}" 2>/dev/null; then
  parent="$(git rev-parse "refs/remotes/${remote}/${branch}")"
  if [ "$(git rev-parse "${parent}^{tree}")" = "$tree" ]; then
    echo "No change: ${branch} already contains the current graph."
    exit 0
  fi
fi

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-github-actions[bot]}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"

if [ -n "$parent" ]; then
  commit="$(git commit-tree "$tree" -p "$parent" -m "$message")"
else
  commit="$(git commit-tree "$tree" -m "$message")"
fi

if [ "${GITGRAPH_DRY_RUN:-false}" = "true" ]; then
  echo "Dry run: would push ${commit} to ${remote}/${branch}"
  exit 0
fi
# Fast-forward only: never force-push.
git push --quiet "$remote" "${commit}:refs/heads/${branch}"
echo "Published ${commit} to ${remote}/${branch}"
