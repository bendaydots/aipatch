#!/usr/bin/env python3
import sys
import os
import re
import json
import argparse
import datetime
import subprocess
import pyperclip

try:
    from . import prelude
except ImportError:
    import prelude

# --- Constants for Patch Logic ---
AIPATCH_DIR = ".aipatch"
REPORT_FILE = "last_run.json"
SEPARATOR = "-----------------====!!!====-----------------"

FENCE_RE = re.compile(
    r'(?P<fence>(`{3,}|~{3,}))(?P<lang>[^\n]*)\n(?P<content>.*?)(?P=fence)',
    re.DOTALL
)
SEARCH_MARK_RE = re.compile(r'^\s*<+\s*SEARCH\s*$', re.IGNORECASE)
REPLACE_MARK_RE = re.compile(r'^\s*>+\s*REPLACE\s*$', re.IGNORECASE)


# --- Helper Functions: Patch Logic ---

def _clean_path(line: str) -> str:
    s = line.strip()
    for prefix in ("//", "#", "--", ";", "'"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    s = re.sub(r'^(?:/\*+|<!--)\s*', '', s).strip()
    s = re.sub(r'\s*(?:\*+/|-->)\s*$', '', s).strip()
    s = s.strip('`"\'')
    if s.startswith("./"):
        s = s[2:]
    if s.startswith("/") and not os.path.exists(s):
        s = s.lstrip("/")
    return s

def parse_blocks(text, project_filter=None):
    edits = []
    for m in FENCE_RE.finditer(text):
        raw_fence = m.group(0)
        lang = (m.group("lang") or "").strip()
        fence_id = lang.split()[0].lower() if lang else None
        is_summary_block = (fence_id is not None and "summary" in fence_id)

        if project_filter and not is_summary_block and fence_id != project_filter.lower():
            continue

        block = m.group("content")
        lines = block.splitlines()
        if not lines:
            continue

        i = 0
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            continue
        file_path = _clean_path(lines[i])
        i += 1

        search_idx = sep_idx = replace_idx = None
        for idx in range(i, len(lines)):
            line = lines[idx]
            if search_idx is None and SEARCH_MARK_RE.match(line):
                search_idx = idx
            elif search_idx is not None and sep_idx is None and line.strip() == '=======':
                sep_idx = idx
            elif sep_idx is not None and replace_idx is None and REPLACE_MARK_RE.match(line):
                replace_idx = idx
                break
        if None in (search_idx, sep_idx, replace_idx):
            continue

        search_text = "\n".join(lines[search_idx + 1:sep_idx])
        replace_text = "\n".join(lines[sep_idx + 1:replace_idx])
        edits.append((file_path, search_text, replace_text, raw_fence, fence_id))
    return edits

def _rfc3339_now():
    return datetime.datetime.now().astimezone().isoformat()

def _safe_ts_for_filename(ts: str) -> str:
    return ts.replace(":", "-")

def _ensure_aipatch_and_log_input(input_text: str):
    os.makedirs(AIPATCH_DIR, exist_ok=True)
    ts = _rfc3339_now()
    log_path = os.path.join(AIPATCH_DIR, "inputs.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(SEPARATOR + "\n")
        f.write(ts + "\n")
        f.write(input_text)
        if not input_text.endswith("\n"):
            f.write("\n")
    return ts

class RunReport:
    def __init__(self, ts: str):
        self.ts = ts
        self.applied = []
        self.failures = []

    def record_success(self, path: str, project: str = None):
        self.applied.append({"file": path, "project": project})

    def record_failure(self, path: str, reason: str, block: str, project: str = None):
        self.failures.append({
            "file": path,
            "reason": reason,
            "project": project,
            "block": block
        })

    def save(self):
        data = {
            "timestamp": self.ts,
            "stats": {
                "total": len(self.applied) + len(self.failures),
                "applied": len(self.applied),
                "failed": len(self.failures)
            },
            "applied_files": self.applied,
            "failures": self.failures
        }
        path = os.path.join(AIPATCH_DIR, REPORT_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

def apply_edits(edits, report: "RunReport|None" = None):
    applied_count = 0
    applied_files = set()

    for file_path, search_text, replace_text, raw_fence, project in edits:
        target = file_path

        if target == os.path.join(AIPATCH_DIR, "LAST-SUMMARY.md"):
            if os.path.exists(target):
                os.remove(target)
            search_text = ""

        if search_text == "" and replace_text != "":
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(replace_text)
            print(f"[CREATE] {target}")
            applied_count += 1
            applied_files.add(target)
            if report:
                report.record_success(target, project)
            continue

        if not os.path.exists(target):
            reason = "File not found"
            print(f"[WARN] {reason}: {target}", file=sys.stderr)
            if report:
                report.record_failure(target, reason, raw_fence, project)
            continue

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            orig = f.read()

        pos = orig.find(search_text)
        if pos == -1:
            reason = "SEARCH text not found"
            print(f"[WARN] {reason} in {target}", file=sys.stderr)
            if report:
                report.record_failure(target, reason, raw_fence, project)
            continue

        patched = orig.replace(search_text, replace_text, 1)
        with open(target, "w", encoding="utf-8") as f:
            f.write(patched)
        print(f"[APPLY] {target}")
        applied_count += 1
        applied_files.add(target)
        if report:
            report.record_success(target, project)

    return applied_count, list(applied_files)


# --- Subcommand: PRELUDE ---

def run_prelude(args):
    print(prelude.PRELUDE_TEXT)


# --- Subcommand: CLIP ---

def run_clip(args):
    env_project = os.getenv("AIPATCH_PROJECT")
    project = args.project if args.project is not None else env_project

    if not args.stdout and sys.stdin.isatty():
        print("Enter filenames (one per line), finish with Ctrl+D (Linux/macOS) or Ctrl+Z (Windows):")

    files = [line.strip() for line in sys.stdin if line.strip()]
    if not files:
        if not args.stdout:
            print("No files entered.")
        return

    parts = []
    for fname in files:
        if not os.path.isfile(fname):
            if not args.stdout:
                print(f"Warning: '{fname}' does not exist or is not a file. Skipping.")
            continue
        try:
            with open(fname, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            if not args.stdout:
                print(f"Error reading '{fname}': {e}. Skipping.")
            continue

        if project:
            header = f"File: {fname} (project: {project})"
        else:
            header = f"File: {fname}"

        parts.append(f"\n\n{header}\n{'-'*22}\n{content}\n")

    if not parts:
        if not args.stdout:
            print("No valid files found.")
        return

    output = "\n".join(parts)

    if args.stdout:
        sys.stdout.write(output)
    else:
        pyperclip.copy(output)
        print(f"\nCopied {len(parts)} files to clipboard in LLM format.")


# --- Subcommand: PATCH ---

def run_patch(args):
    # Read input from stdin
    if sys.stdin.isatty():
         print("Waiting for input. Paste patch content and press Ctrl+D:")
    data = sys.stdin.read()

    # Ensure .aipatch exists and log input
    ts = _ensure_aipatch_and_log_input(data)
    report = RunReport(ts)

    edits = parse_blocks(data, args.project)
    if not edits:
        print("[ERROR] No edits found", file=sys.stderr)
        sys.exit(1)

    applied_count, applied_files = apply_edits(edits, report=report)
    report_path = report.save()

    if applied_count == 0:
        print(f"[ERROR] No edits applied. See report: {report_path}", file=sys.stderr)
        sys.exit(1)

    if report.failures:
        print(f"[WARN] {len(report.failures)} patches failed. See report: {report_path}", file=sys.stderr)

    print(f"[OK] Applied {applied_count} edits to {len(applied_files)} files.")

    # --- Git operations ---
    summary_path = os.path.join(AIPATCH_DIR, "LAST-SUMMARY.md")
    files_to_stage = [f for f in applied_files if f != summary_path]

    should_stage = args.git or args.git_commit
    if should_stage and files_to_stage:
        try:
            print(f"[GIT] Staging {len(files_to_stage)} files...")
            subprocess.run(["git", "add"] + files_to_stage, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[ERROR] `git add` failed: {e}", file=sys.stderr)
            if args.git_commit:
                sys.exit(1)

    if args.git_commit:
        if not os.path.exists(summary_path):
            print(f"[WARN] Summary file not found at {summary_path}. Skipping commit.", file=sys.stderr)
            return

        with open(summary_path, "r", encoding="utf-8") as f:
            if not f.read().strip():
                print("[WARN] Summary file is empty. Skipping commit.", file=sys.stderr)
                return

        if not files_to_stage:
            print("[INFO] No application files changed, only summary. Skipping commit.", file=sys.stderr)
            return

        try:
            print(f"[GIT] Committing with message from {summary_path}...")
            subprocess.run(["git", "commit", "-a", "-F", summary_path], check=True)
            print(f"[OK] Committed changes to {len(files_to_stage)} files.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"[ERROR] `git commit` failed: {e}", file=sys.stderr)
            sys.exit(1)

    # --- Print all projects mentioned in input ---
    project_names = set()
    for m in FENCE_RE.finditer(data):
        lang = (m.group("lang") or "").strip()
        fence_id = lang.split()[0].lower() if lang else None
        if not fence_id or "summary" in fence_id:
            continue
        project_names.add(fence_id)

    if project_names:
        print("Projects found:", " ".join(sorted(project_names)))


# --- Subcommand: PBCOPY ---

def run_pbcopy(args):
    content = sys.stdin.read()
    pyperclip.copy(content)


# --- Subcommand: PBPASTE ---

def run_pbpaste(args):
    content = pyperclip.paste()
    sys.stdout.write(content)


# --- Subcommand: LAST ---

def run_last(args):
    report_path = os.path.join(AIPATCH_DIR, "last_run.json")
    if not os.path.exists(report_path):
        print(f"[ERROR] No report found at {report_path}", file=sys.stderr)
        sys.exit(1)

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    failures = data.get("failures", [])
    mode = args.mode

    if mode == "list":
        # Just list the status
        print(f"Report from: {data.get('timestamp')}")
        print(f"Applied: {data.get('stats', {}).get('applied', 0)}")
        print(f"Failed:  {len(failures)}")
        if failures:
            print("\nFailures:")
            for fail in failures:
                p_str = f" [{fail['project']}]" if fail.get('project') else ""
                print(f"  - {fail['file']}: {fail['reason']}{p_str}")

    elif mode == "fix":
        # Generate prompt to FIX
        if not failures:
            print("No failures to fix.")
            return

        print("The following patches failed to apply. Please FIX the SEARCH blocks.\n")
        for fail in failures:
            path = fail['file']
            reason = fail['reason']
            project = fail.get('project')
            raw_block = fail['block']

            p_header = f" (project: {project})" if project else ""
            print(f"File: {path}{p_header}")
            print(f"Error: {reason}")
            print(f"Attempted Patch:\n{raw_block}")

            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                print(f"Current File Content:\n{SEPARATOR}\n{content}\n{SEPARATOR}\n")
            else:
                print("Current File Content: (File does not exist)\n")

    elif mode == "why":
        # Generate prompt to ANALYZE
        if not failures:
            print("No failures to analyze.")
            return

        print("The following patches failed. Please ANALYZE why.\n")
        print("Check for:\n1. Lazy comments (e.g. // ...)\n2. Indentation mismatch (Tabs vs Spaces)\n3. Patch already applied\n4. Incorrect context matching\n")
        for fail in failures:
            path = fail['file']
            reason = fail['reason']
            raw_block = fail['block']
            print(f"File: {path}")
            print(f"Error: {reason}")
            print(f"Block:\n{raw_block}\n")


# --- Subcommand: HELP ---

def run_help(args):
    print("""aipatch: Tool for LLM context gathering and patch application.

Usage:
  aipatch <command> [options]

Commands:
  prelude
      Output the standard prompt instructions (prelude) for the LLM.

  clip
      Combines multiple files into a format suitable for the LLM.
      Reads file paths from stdin (one per line).
      By default, copies the result to the clipboard.

      Options:
        --project <NAME>  : Add a project context identifier to the file headers.
                            (Env: AIPATCH_PROJECT)
        --stdout          : Print result to stdout instead of copying to clipboard.

  patch
      Parses and applies code modifications (SEARCH/REPLACE blocks) generated by the LLM.
      Reads the response text from stdin.

      Options:
        --project <NAME>  : Only apply blocks matching the specific project fence.
        --git             : Automatically `git add` modified files.
        --git-commit      : Automatically `git add` and `git commit` using the provided summary.

  pbcopy
      Utility to copy stdin to the system clipboard.

  pbpaste
      Utility to print system clipboard content to stdout.

  help
      Show this help message.
""")


# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="aipatch: Tool for LLM context gathering and patch application.")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Sub-command to run")

    # 'prelude' command
    parser_prelude = subparsers.add_parser("prelude", help="Output the prelude prompt.")
    parser_prelude.set_defaults(func=run_prelude)

    # 'clip' command
    parser_clip = subparsers.add_parser("clip", help="Combine files for LLM context")
    parser_clip.add_argument("--project", help="Project name (overrides AIPATCH_PROJECT env).")
    parser_clip.add_argument("--stdout", action="store_true", help="Print to stdout instead of copying to clipboard.")
    parser_clip.set_defaults(func=run_clip)

    # 'patch' command
    parser_patch = subparsers.add_parser("patch", help="Apply LLM generated patches")
    parser_patch.add_argument("--project", help="Only apply blocks with matching fence language", default=None)
    parser_patch.add_argument("--git", action="store_true", help="Run `git add` for every patched file")
    parser_patch.add_argument("--git-commit", action="store_true", help="Stages patched files and commits using the summary file.")
    parser_patch.set_defaults(func=run_patch)

    # 'pbcopy' command
    parser_pbcopy = subparsers.add_parser("pbcopy", help="Read stdin and copy to clipboard.")
    parser_pbcopy.set_defaults(func=run_pbcopy)

    # 'pbpaste' command
    parser_pbpaste = subparsers.add_parser("pbpaste", help="Print clipboard content to stdout.")
    parser_pbpaste.set_defaults(func=run_pbpaste)

    # 'last' command
    parser_last = subparsers.add_parser("last", help="Query the last patch run (requires last_run.json).")
    parser_last.add_argument("mode", nargs="?", choices=["list", "fix", "why"], default="list",
                             help="list: Show summary (default). fix: Gen prompt to fix. why: Gen prompt to analyze.")
    parser_last.set_defaults(func=run_last)

    # 'help' command
    parser_help = subparsers.add_parser("help", help="Show detailed help and usage.")
    parser_help.set_defaults(func=run_help)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()