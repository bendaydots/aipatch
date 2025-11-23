# aipatch

A combined utility for interacting with LLMs.

## Installation

```bash
pip install .
```

## Usage

### 1. aipatch clip
Gathers file context (like `aiclip.py`). Reads filenames from stdin.

```bash
# Find python files and put content on clipboard with project tag 'ai01'
find . -name "*.py" | aipatch clip --project ai01
```

### 2. aipatch patch
Applies search/replace blocks (like `aipatch.py`). Reads patch content from stdin.

```bash
# Apply patch from clipboard
pbpaste | aipatch patch --git
```