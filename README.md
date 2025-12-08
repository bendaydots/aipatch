# aipatch

`aipatch` is a CLI tool designed to streamline the "Context Gathering -> LLM Prompting -> Code Application" loop. It formats codebases for LLMs and applies the structured responses returned to your files.

[![I improved aipatch Using aipatch](media/video-image2.jpg)](https://youtu.be/xho0pMKPu14)

## Why aipatch?
Most AI coding tools (Cursor, aider, Gemini CLI, Copilot Edits) automate patching,  
but they give you **very little control** over the context actually sent to the LLM.  
Without the right content (or with no context), the LLM makes wrong assumptions, which leads compounded mistakes.
And if the context is bloated, the LLM will break the SEARCH/REPLACE formatting.

**aipatch solves this by letting you manually control the exact context** being sent to the LLM 
while still automating 90% of the workflow.

Key reasons to use it:

- You select exactly which files are sent to the LLM.
- You can combine multiple repositories, languages, and commits into a single mega-prompt.
- You can edit backend + frontend + docs + mobile in one LLM pass.
- You avoid the endless “fix your patch” loop common in automated tools.

## Features at a glance
- **Multi-project prompting** using project IDs (`backend`, `web`, `docs`, `android`)
- Build **mega-prompts up to 1M tokens** (Google AI Studio / Gemini)
- Full-stack feature development: backend + frontend + docs + mobile in one pass
- Cross-language editing (Go → Kotlin, Python → TS, etc.)
- Commit-to-commit debugging via LLM context
- Deterministic SEARCH/REPLACE patching with diagnostics
- Editor-independent workflow (pure CLI)
- Works with any LLM (ChatGPT, Claude, Gemini, local models)

## Installation

```bash
# Standard pip
pip install --upgrade aipatch

# pipx (Recommended)
pipx install aipatch

# uv
uvx aipatch --help
```

## Multi-Project Prompting (Unique Feature)

Unlike other AI coding tools which only operate inside a single repository,  
**aipatch can collect context from multiple projects, languages, and git commits**,  
merging them into one structured prompt with project IDs.

This enables:

- Editing backend + frontend simultaneously  
- Updating documentation alongside the code  
- Porting features between different repos  
- Cross-language translation (e.g., Go → Kotlin, Python → TS)
- Using one project as reference architecture for another  
- Comparing OLD vs NEW git commits in a single prompt  
- Implementing mobile (Android/iOS) clients based on backend + frontend context  

Example real-world workflow:

You can ask the LLM:  
> “Add the new `/user/settings/update` API, update backend, update the web frontend,  
> update the API documentation, and implement the same API usage in the Android app.”

And `aipatch` provides the context necessary for the LLM  
to update the **entire stack in one iteration**.

## Workflow

### 1. Gather Context (The Prompt)

The goal is to generate a single text block containing the "Rules" (prelude) and the "Code" (clip) to paste into your LLM.

#### Basic: Single Project
Combine the system instructions with all Python files in the current directory.

```bash
# Get the standard prompt rules
RULE="$(aipatch prelude)"

# Get file contents (using ripgrep to list files)
CODE="$(rg --files -g '!venv' | rg '\.py$' | aipatch clip --stdout --project my_app)"

# Copy to clipboard
printf "%s\n\n%s\n" "$RULE" "$CODE" | pbcopy
```

#### Advanced: Multi-Project Context
When you need to modify an API and a frontend simultaneously, you can capture context from different directories and assign them distinct project IDs.

```bash
#!/bin/bash

# 1. Get the Rules
RULE="$(aipatch prelude)"

# 2. Get Backend Code
cd ~/projects/backend-api
GO_CODE="$(rg --files | rg '\.go$' | aipatch clip --stdout --project backend)"
# Add specific documentation
GO_CODE="$GO_CODE$(echo 'docs/api-spec.md' | aipatch clip --stdout --project backend)"

# 3. Get Frontend Code
cd ~/projects/mobile-app
# Get Kotlin code and the Manifest
KOTLIN_CODE="$(rg --files | rg '\.kt$' | aipatch clip --stdout --project android)"
MANIFEST="$(echo 'app/src/main/AndroidManifest.xml' | aipatch clip --stdout --project android)"

# 4. Combine and Copy
printf "%s\n%s\n%s\n%s\n" "$RULE" "$GO_CODE" "$KOTLIN_CODE" "$MANIFEST" | pbcopy

echo "Copied context for Backend and Android to clipboard."
```

#### Expert: Git Branch Comparison (Time Travel)
Useful when asking an LLM to analyze changes between a refactor and the original code.

```bash
#!/bin/bash

RULE="$(aipatch prelude)"

# 1. Capture the OLD state
git switch legacy-branch
OLD_CODE="$(rg --files | rg '\.kt$' | aipatch clip --stdout --project legacy)"

# 2. Capture the NEW state
git switch main
NEW_CODE="$(rg --files | rg '\.kt$' | aipatch clip --stdout --project refactor)"

# 3. Combine
printf "%s\n\n# --- OLD VERSION ---\n%s\n\n# --- NEW VERSION ---\n%s\n" "$RULE" "$OLD_CODE" "$NEW_CODE" | pbcopy
```

---

### 2. Apply Changes (The Patch)

Once the LLM generates a response containing `*SEARCH/REPLACE*` blocks, copy that response to your clipboard.

#### Basic Apply
Reads the LLM response from the clipboard and applies it.

```bash
aipatch pbpaste | aipatch patch
```

#### Apply with Git Commit
Automatically stages changed files and commits them using the summary generated by the LLM.

```bash
aipatch pbpaste | aipatch patch --git-commit
```

#### Apply to Specific Project Only
If your prompt included multiple projects (e.g., `backend` and `android`), but the LLM provided one big response, you can choose to apply only the `android` changes first.

```bash
aipatch pbpaste | aipatch patch --git-commit --project android
```

---

## Command Reference

| Command | Description |
| :--- | :--- |
| `aipatch prelude` | Outputs the standard system prompt/rules for the LLM. |
| `aipatch clip` | Reads filenames from stdin and formats their content. Use `--stdout` to pipe results. |
| `aipatch patch` | Reads LLM response from stdin and applies edits. |
| `aipatch pbcopy` | Utility to copy stdin to system clipboard. |
| `aipatch pbpaste` | Utility to print system clipboard to stdout. |

### Common Flags
*   `--project <name>`: Tags the code block with a project ID (e.g., `backend`, `ios`). Essential for multi-repo edits.
*   `--git-commit`: (For `patch`) Stages changes and commits with the LLM's summary.