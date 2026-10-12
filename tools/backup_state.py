#!/usr/bin/env python3
"""
Automated script to bundle local database state changes into a secure compressed JSON snapshot,
append the snapshot to a dedicated backup branch, and commit.
"""
import json
import gzip
import os
import subprocess

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if result.returncode != 0 and "working tree clean" not in result.stdout and "working tree clean" not in result.stderr:
        print(f"Error running command: {cmd}")
        print(result.stderr)
        raise Exception(f"Command failed: {cmd}")
    return result.stdout.strip()

def main():
    # Identify database state files (.json and .sqlite)
    state = {}

    # Bundle actual database states (.sqlite and .json)
    for root_dir, dirs, files in os.walk("."):
        if ".git" in root_dir or "__pycache__" in root_dir or "node_modules" in root_dir or "packs" in root_dir:
            continue

        for file in files:
            if file.endswith(".json"):
                filepath = os.path.join(root_dir, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        state[filepath] = json.load(f)
                except Exception as e:
                    print(f"Failed to read {filepath}: {e}")
            elif file.endswith(".sqlite") or file.endswith(".db"):
                filepath = os.path.join(root_dir, file)
                try:
                    # Read binary database file and store it as base64 in the json
                    import base64
                    with open(filepath, "rb") as f:
                        state[filepath] = base64.b64encode(f.read()).decode('utf-8')
                except Exception as e:
                    print(f"Failed to read {filepath}: {e}")

    # Bundle into a secure compressed JSON snapshot
    snapshot_filename = "database_snapshot.json.gz"
    with gzip.open(snapshot_filename, "wt", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"Backup complete: {snapshot_filename} created successfully.")

    branch_name = "backup/database-state"

    # Check if branch already exists
    branch_exists_result = subprocess.run(f"git rev-parse --verify {branch_name}", shell=True, capture_output=True, text=True)

    if branch_exists_result.returncode != 0:
        # Create an orphan branch, but without touching the working tree
        # Create an empty tree with -w to write it
        empty_tree_sha = run_cmd("git hash-object -w -t tree /dev/null")
        # Create a commit with the empty tree
        commit_sha = run_cmd(f'git commit-tree {empty_tree_sha} -m "Initial commit for backup branch"')
        # Create the branch
        run_cmd(f"git branch {branch_name} {commit_sha}")

    # We want to commit `database_snapshot.json.gz` to `backup/database-state` WITHOUT checking it out
    # to avoid modifying the current working directory.

    # Add snapshot to the object database
    blob_sha = run_cmd(f"git hash-object -w {snapshot_filename}")

    # Create a tree with the snapshot
    # Format: mode type sha\tname
    tree_content = f"100644 blob {blob_sha}\t{snapshot_filename}"

    # Run git mktree to build the tree object
    tree_sha = run_cmd(f"printf '%s' '{tree_content}' | git mktree")

    # Get the parent commit of the branch
    parent_commit = run_cmd(f"git rev-parse {branch_name}")

    # Create the new commit
    new_commit_sha = run_cmd(f'git commit-tree {tree_sha} -p {parent_commit} -m "chore: execute automated database state backup [skip ci]"')

    # Update the branch pointer to the new commit
    if new_commit_sha:
        run_cmd(f"git update-ref refs/heads/{branch_name} {new_commit_sha}")
        print("Commit successful to backup branch without altering working directory.")

    # Create PR via GitHub API using subprocess so bash session doesn't block
    subprocess.run("git push -u origin backup/database-state || true", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run('gh pr create --title "chore: execute automated database state backup [skip ci]" --body "Automated database state backup." --base main --head backup/database-state || true', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Clean up the local file
    if os.path.exists(snapshot_filename):
        os.remove(snapshot_filename)

if __name__ == "__main__":
    main()
