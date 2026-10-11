# Agent Commands, Tooling & Prompting Reference (`drive-audit-cli`)

This reference documents the commands, tools, execution mechanisms, and prompts used by the **Antigravity AI Agent** while assisting and supporting the `drive-audit-cli` project.

---

## 📑 Table of Contents

1. [Overview of the Agent Execution Model](#1-overview-of-the-agent-execution-model)
2. [Agent Tool Commands (What the Agent Executes)](#2-agent-tool-commands-what-the-agent-executes)
   - [Terminal & Execution Management](#terminal--execution-management)
   - [Code & Filesystem Operations](#code--filesystem-operations)
   - [Inspection & Search](#inspection--search)
   - [User Interaction & Prompting](#user-interaction--prompting)
   - [Web & Browser Subagents](#web--browser-subagents)
   - [Background Timers & Schedulers](#background-timers--schedulers)
3. [Terminal Commands Executed by the Agent on the System](#3-terminal-commands-executed-by-the-agent-on-the-system)
   - [Git & Version Control](#git--version-control)
   - [Python & Runtime Execution](#python--runtime-execution)
   - [macOS Hardware & System Discovery](#macos-hardware--system-discovery)
   - [SQLite Database Queries & Admin](#sqlite-database-queries--admin)
   - [Extended Attributes & Tagging (`xattr`)](#extended-attributes--tagging-xattr)
   - [iDrive Backup Plist Operations](#idrive-backup-plist-operations)
   - [Filesystem Maintenance & Cleanups](#filesystem-maintenance--cleanups)
4. [Slash Commands & User Prompts (What You Can Prompt)](#4-slash-commands--user-prompts-what-you-can-prompt)
   - [`/plan`](#plan)
   - [`/goal`](#goal)
   - [`/grill-me`](#grill-me)
   - [`/learn`](#learn)
   - [`/schedule`](#schedule)
5. [How the Agent Prompts You (Decision Gates & Interactive Modals)](#5-how-the-agent-prompts-you-decision-gates--interactive-modals)
6. [Agent Customizations, Skills & Knowledge Items](#6-agent-customizations-skills--knowledge-items)

---

## 1. Overview of the Agent Execution Model

When you interact with the agent, the system operates as an autonomous pair-programmer:
- **Autonomous Tool Execution**: The agent invokes specialized tools directly to read files, search the codebase, edit code, execute shell commands, and inspect system state.
- **Terminal Integration**: Shell commands are executed natively in macOS `zsh` within your workspace directory (`/Users/nickolaycohen/dev/drive-audit-cli`).
- **Reactive Notification & Background Tasks**: Long-running commands (like test runs or scans) can be sent to the background; the system notifies the agent asynchronously upon completion without busy-waiting.
- **Artifact Generation**: Detailed plans, research notes, and status reports are written to the session artifact store and rendered directly in your IDE.

---

## 2. Agent Tool Commands (What the Agent Executes)

Below is the complete reference of built-in agent tool commands available to the agent:

### Terminal & Execution Management

#### `run_command`
Executes shell commands directly in your local environment.
- **Syntax / Parameters**:
  - `CommandLine` (string): The shell command line to run (e.g., `git status`, `python3 benchmark_drives.py`).
  - `Cwd` (string): Working directory (must be inside workspace, e.g., `/Users/nickolaycohen/dev/drive-audit-cli`).
  - `WaitMsBeforeAsync` (int): Milliseconds to wait synchronously before detaching to background (e.g., `5000`).
  - `IsDaemon` (bool): `true` for continuous processes like dev servers or watchers.
  - `RunPersistent` (bool): `true` to preserve environment variables across calls.
- **Example Usage**:
  ```json
  {
    "CommandLine": "git log -n 5 --oneline",
    "Cwd": "/Users/nickolaycohen/dev/drive-audit-cli",
    "WaitMsBeforeAsync": 5000
  }
  ```

#### `manage_task`
Interacts with running background tasks launched by `run_command` or `schedule`.
- **Syntax / Parameters**:
  - `Action`: `'list'` (view all active tasks), `'status'` (check execution log), `'send_input'` (send stdin), `'kill'` (abort).
  - `TaskId` (string): Unique task identifier.
  - `Input` (string): Text input when `Action` is `'send_input'`.
- **Explanation**: Allows the agent to send interactive keys (`q`, `Enter`, numbers) to running CLI processes or terminate hung tasks.

---

### Code & Filesystem Operations

#### `view_file`
Reads the content of text files, scripts, markdown, images, or PDFs.
- **Syntax / Parameters**:
  - `AbsolutePath` (string): Absolute path to target file (e.g., `/Users/nickolaycohen/dev/drive-audit-cli/README.md`).
  - `StartLine` (int, optional): Starting line (1-indexed).
  - `EndLine` (int, optional): Ending line (up to 800 lines per call).
  - `ContentOffset` (int, optional): Byte offset for large binary/text files.
- **Explanation**: Used to inspect source code, SQL queries, and configuration files with exact line numbers.

#### `write_to_file`
Creates new files or replaces complete files.
- **Syntax / Parameters**:
  - `TargetFile` (string): Absolute path to create/write.
  - `CodeContent` (string): File content.
  - `Overwrite` (bool): Set `true` to replace existing files.
  - `ArtifactMetadata` (object, optional): Used when writing IDE artifacts.
- **Explanation**: Used when authoring new documentation files (like `common-commands.md`) or initializing scripts.

#### `replace_file_content`
Makes a single, contiguous replacement in an existing file.
- **Syntax / Parameters**:
  - `TargetFile` (string): Absolute path.
  - `StartLine` / `EndLine` (int): Boundary containing target text.
  - `TargetContent` (string): Exact lines to match.
  - `ReplacementContent` (string): New code replacing the target content.
  - `AllowMultiple` (bool): Allow replacing multiple identical matches.

#### `multi_replace_file_content`
Makes multiple non-contiguous edits across a file in a single atomic operation.
- **Syntax / Parameters**:
  - `TargetFile` (string): Absolute path.
  - `ReplacementChunks` (array): List of `{StartLine, EndLine, TargetContent, ReplacementContent}` objects.
- **Explanation**: Ideal for refactoring multiple functions or imports simultaneously without rewriting the entire file.

---

### Inspection & Search

#### `grep_search`
Performs high-speed regex or literal text searches across the repository using `ripgrep`.
- **Syntax / Parameters**:
  - `SearchPath` (string): Directory or file path.
  - `Query` (string): Pattern or search string.
  - `IsRegex` (bool): Regex mode flag.
  - `CaseInsensitive` (bool): Case-insensitive flag.
  - `MatchPerLine` (bool): Return line numbers and content snippets.
  - `Includes` (array): File globs (e.g. `["*.py"]`, `["*.sql"]`).

#### `list_dir`
Lists all files and subdirectories inside a directory.
- **Syntax / Parameters**:
  - `DirectoryPath` (string): Absolute directory path.
- **Explanation**: Returns item names, sizes, directory flags, and child counts.

---

### User Interaction & Prompting

#### `ask_question`
Renders an interactive modal dialog directly in your IDE to prompt you for decisions.
- **Syntax / Parameters**:
  - `questions` (array of objects):
    - `question` (string): The prompt displayed to you.
    - `options` (array of strings): Selectable response options (prefixed with `(Recommended)` when suggested).
    - `is_multi_select` (bool): `true` for checkboxes, `false` for single-choice radio buttons.
- **Explanation**: Used by the agent when it needs your explicit guidance on architectural directions, branch names, file locations, or feature scopes before proceeding.

---

### Web & Browser Subagents

#### `search_web`
Performs external web searches for technical documentation, library APIs, and error messages.
- **Syntax / Parameters**:
  - `query` (string): Search query.
  - `domain` (string, optional): Specific domain to prioritize (e.g., `developer.apple.com`, `docs.python.org`).

#### `read_url_content`
Fetches and converts public web pages to markdown via HTTP without opening a browser.
- **Syntax / Parameters**:
  - `Url` (string): Web URL to fetch.

#### `browser_subagent`
Spawns an autonomous browser agent that navigates web pages, clicks, fills inputs, and records session videos.
- **Syntax / Parameters**:
  - `Task` (string): Detailed instructions for the subagent.
  - `TaskName` (string): High-level title.
  - `RecordingName` (string): Name of the generated WebP session video.

---

### Background Timers & Schedulers

#### `schedule`
Schedules one-shot reminder timers or recurring cron triggers.
- **Syntax / Parameters**:
  - `DurationSeconds` (string): Seconds to wait before firing a high-priority agent notification.
  - `CronExpression` (string): 5-field cron expression for recurring tasks (e.g., `*/10 * * * *`).
  - `Prompt` (string): The message delivered back to the agent when the timer triggers.
  - `TimerCondition` (string): Early cancellation condition (`never`, `any`, or specific task ID).

---

## 3. Terminal Commands Executed by the Agent on the System

During the development and maintenance of `drive-audit-cli`, the agent executes these specific shell commands via `run_command` in `/Users/nickolaycohen/dev/drive-audit-cli`:

### Git & Version Control

```bash
# Check working tree status and modified files
git status

# Inspect recent commits
git log -n 15 --oneline

# View diff of unstaged changes
git diff

# View diff of staged changes
git diff --staged

# Stage specific files
git add README.md drive_audit_finder.py

# Commit with conventional commit prefixes
git commit -m "feat: add read-only benchmark fallback"
git commit -m "fix: clarify Time Machine backup protection status"
git commit -m "perf: optimize report queries using CTEs"

# Push to origin repository
git push origin main
```

### Python & Runtime Execution

```bash
# Run the main interactive storage orchestrator via shortcut launcher
./run.sh

# Or invoke directly via Python
python3 python/drive_audit_finder.py

# Run with custom SQLite database path override
DRIVE_AUDIT_DB="/path/to/drive_audit.db" python3 python/drive_audit_finder.py

# Benchmark all mounted volumes (256 MB payload)
python3 python/benchmark_drives.py

# Quick 64 MB benchmark
python3 python/benchmark_drives.py --quick

# Benchmark a specific target drive
python3 python/benchmark_drives.py --target /Volumes/LaCie

# Custom payload size benchmark
python3 python/benchmark_drives.py --size-mb 512

# Output machine-readable JSON metrics
python3 python/benchmark_drives.py --json

# Interactive benchmark menu
python3 python/benchmark_drives.py --interactive
```

### macOS Hardware & System Discovery

```bash
# Inspect drive protocol, SSD/HDD media, filesystem & Time Machine flag
diskutil info /Volumes/LaCie
diskutil info /Volumes/Extreme\ Pro

# List all internal and external partition tables
diskutil list

# Query macOS network host name for host tracking in SQLite
scutil --get LocalHostName

# Pre-query cached Finder folder size before initiating scan
osascript -e 'tell application "Finder" to get size of (POSIX file "/Volumes/LaCie/Storage" as alias)'

# Check if iDrive application is running before updating plists
pgrep -f "/Applications/IDrive.app"
```

### SQLite Database Queries & Admin

```bash
# Connect to canonical database
sqlite3 "/Volumes/Extreme Pro/Data/sqlite/drive-audit/drive_audit.db"

# List database tables
sqlite3 drive_audit.db ".tables"

# View complete schema definition
sqlite3 drive_audit.db ".schema"

# Check Write-Ahead Logging (WAL) mode
sqlite3 drive_audit.db "PRAGMA journal_mode;"

# Execute batch analytical queries
sqlite3 -header -column drive_audit.db < queries.sql

# Calculate global recoverable duplicate GB
sqlite3 -header -column drive_audit.db "
SELECT COUNT(*) AS groups, SUM(copy_count - 1) AS dups,
ROUND(SUM((copy_count - 1) * size_bytes) / 1024.0 / 1024.0 / 1024.0, 2) AS recoverable_gb
FROM (SELECT name, size_bytes, COUNT(*) AS copy_count FROM files WHERE size_bytes > 0 GROUP BY name, size_bytes HAVING COUNT(*) > 1);"
```

### Extended Attributes & Tagging (`xattr`)

```bash
# Inspect raw Finder tags extended attribute
xattr -p com.apple.metadata:_kMDItemUserTags "/Volumes/LaCie/Storage/Priority 1"

# Convert binary plist tag attribute to readable XML
xattr -p com.apple.metadata:_kMDItemUserTags "/path" | plutil -convert xml1 - -o -

# Strip Finder color and label tags from directory
xattr -d com.apple.metadata:_kMDItemUserTags "/path/to/folder"

# Clear all extended attributes on a file or folder
xattr -c "/path/to/folder"
```

### iDrive Backup Plist Operations

```bash
# Pretty-print active external drive backup paths
plutil -p "/Library/Application Support/IDrive/Mac/IDriveData/<User>/NetworkDriveBackupSet.plist"

# Pretty-print active local drive backup paths
plutil -p "/Library/Application Support/IDrive/Mac/IDriveData/<User>/backupReferenceFile.plist"

# Validate XML/binary plist syntax after updates
plutil -lint "/Library/Application Support/IDrive/Mac/IDriveData/<User>/NetworkDriveBackupSet.plist"
```

### Filesystem Maintenance & Cleanups

```bash
# Check volume capacity and free gigabytes
df -h /Volumes/*

# Summarize directory disk usage
du -sh "/Volumes/LaCie/Storage"/*

# Recursively delete macOS .DS_Store files
find "/Volumes/LaCie/Storage" -name ".DS_Store" -type f -delete

# Recursively delete empty directories left after file migrations
find "/Volumes/LaCie/Storage/Priority 4/Pictures" -type d -empty -delete

# Delete legacy Windows thumbnail caches
find "/Volumes/LaCie/Storage" \( -name "Thumbs.db" -o -name ".picasa.ini" \) -type f -delete
```

---

## 4. Slash Commands & User Prompts (What You Can Prompt)

In the Antigravity chat input, you can trigger specialized modes by typing slash commands:

### `/plan`
- **When to use**: When tackling a complex refactoring or architectural task that requires multi-step planning before execution.
- **Agent Behavior**: The agent creates an implementation plan artifact, identifies dependencies, assesses risks, and waits for your confirmation before changing code.

### `/goal`
- **When to use**: For long-running, autonomous tasks (e.g. overnight batch processing, extensive test fixing, or exhaustive codebase auditing).
- **Agent Behavior**: The agent works persistently without stopping at minor uncertainties, running commands and validating progress until the final objective is fully accomplished.

### `/grill-me`
- **When to use**: When you have an idea or architecture in mind and want the agent to interview you.
- **Agent Behavior**: The agent asks probing questions regarding edge cases, trade-offs, schemas, failure modes, and technical decisions to refine the requirements before implementation.

### `/learn`
- **When to use**: When you corrected a behavior, established a repository rule, or want the agent to remember project-specific preferences forever.
- **Agent Behavior**: Synthesizes the pattern into persistent Knowledge Items (`.agents/` or global customization) so future sessions adhere to your rules automatically.

### `/schedule`
- **When to use**: When you want an instruction to execute on a recurring timer (e.g., every 30 minutes) or set a one-time reminder.
- **Agent Behavior**: Registers a background cron or countdown task that awakens the agent when triggered.

---

## 5. How the Agent Prompts You (Decision Gates & Interactive Modals)

To maintain human governance and ensure you remain in control of critical decisions, the agent prompts you in three distinct ways:

1. **Interactive Modal Dialogs (`ask_question`)**:
   - Renders a GUI modal popup with selectable radio buttons or checkboxes.
   - Example: Asking which storage volume to target or whether to proceed with duplicate deletion.
2. **Artifact Walkthroughs & Approval Gates**:
   - The agent writes structured Markdown plans or audit reports to the artifact pane.
   - You can review the plan and click **Proceed** to authorize execution.
3. **Direct Clarifying Prompts**:
   - Concise conversational questions in chat when requirements are ambiguous or require specific domain context.

---

## 6. Agent Customizations, Skills & Knowledge Items

The agent loads project-specific context and instructions from:

- **Workspace Customizations (`.agents/` / `AGENTS.md` / `GEMINI.md`)**:
  - Contains project-specific architectural rules, coding standards, and prohibited commands.
- **Global Skills (`~/.gemini/config/skills/` & Built-ins)**:
  - `agy-customizations`: Customization workflows, rule creation, and MCP setup.
  - `antigravity-guide`: Reference manual for Google Antigravity features, CLI flags, and keybindings.
- **Knowledge Items (KIs)**:
  - Localized snapshots of known patterns, bug fixes, and database architectures stored in `<appDataDir>/knowledge/`.
