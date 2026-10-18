#!/bin/bash

set -e

echo "🔄 Fetching latest changes..."
git fetch origin automated-indexer-sync
git fetch origin master

echo "🔄 Checking out master..."
git checkout master

echo "🔄 Checking if rebase needed..."
if git merge-base --is-ancestor origin/automated-indexer-sync HEAD; then
    echo "No new changes to merge"
    exit 0
fi

echo "🔄 Rebasing automated-indexer-sync into master..."
if ! git rebase origin/automated-indexer-sync; then
    echo "❌ Rebase failed - conflicts need manual resolution"
    git rebase --abort
    exit 1
fi

echo "🔄 Pushing to master..."
git push origin master

echo "✅ Done"
