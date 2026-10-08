# AgentContract Codex Plugin

This directory contains the standalone Codex plugin packaging for AgentContract.

## Manifest and Directory Layout

```text
integrations/codex-plugin/
├── plugin.json                 # Standard plugin manifest
├── .codex-plugin/
│   └── plugin.json             # Manifest for legacy / alternative plugin discovery
├── hooks/
│   ├── hooks.json              # Hook event declarations (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop)
│   └── agentcontract_hook.py   # Python hook runner entry point
└── README.md                   # This documentation
```

Both `plugin.json` at the plugin root and `.codex-plugin/plugin.json` are provided to ensure full compatibility across Codex versions and discovery mechanisms.

## Installation Options

### 1. Standalone Plugin Installation

Install or symlink this directory into your Codex plugins folder:
- **User-wide**: `~/.codex/plugins/agentcontract`
- **Workspace-local**: `.codex/plugins/agentcontract`

Codex automatically discovers plugins located in these standard plugin search paths.

### 2. Project-Local Hooks (Recommended for Repositories)

Alternatively, install the hooks directly into the current repository using the AgentContract CLI:

```bash
agentcontract codex install --project .
```

This creates `.codex/hooks.json` in your workspace, configured to intercept lifecycle events using the local Python environment.

## Hook Trust Requirements

Codex lifecycle hooks run as external commands with host system privileges. By default, Codex requires explicit trust confirmation before invoking command hooks.

### Trust Configuration
1. **Interactive sessions**: Codex prompts you to trust hooks when opening a workspace or loading a plugin.
2. **Automated/CI runs**: In non-interactive or headless environments (e.g. `codex exec`), pass:
   ```bash
   codex exec --dangerously-bypass-hook-trust -C <workspace_path> "<prompt>"
   ```
3. **Permanent Trust**: Add the plugin or project directory to your trusted projects in `~/.codex/config.toml`:
   ```toml
   [security]
   trusted_directories = ["/path/to/your/project"]
   ```

## Hook Interception Boundary

AgentContract hooks intercept:
- `SessionStart`: Initializes session state and trace log.
- `UserPromptSubmit`: Extracts user constraints into the session `ConstraintLedger`.
- `PreToolUse`: Normalizes tool arguments (file writes, `apply_patch`, shell commands) through `SpecGuard`. Returns exit code 2 and structured `deny` response to abort prohibited actions, and enforces fail-closed policy on opaque shell scripts when HARD filesystem constraints are active.
- `PostToolUse`: Records deterministic tool execution results into `TraceStore`.
- `Stop`: Gathers agent completion prose and validates claims via `EvidenceGate`.
