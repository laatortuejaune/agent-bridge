# Agent Bridge

Local memory continuity between Claude Code and Codex. Import native notes without rewriting them, retrieve project-scoped context, and capture handoffs through lifecycle hooks.

Agent Bridge uses Python's standard library and SQLite. It does not call an additional model or host a network service.

## Requirements

- macOS for installation with the launchd service.
- Python 3.11+ and Git.
- Installed, authenticated Claude Code and Codex versions supporting `SessionStart`, `UserPromptSubmit`, and `Stop` command hooks.

The core and isolated tests also run on Linux. Windows is not supported. Native memory formats and hook interfaces can change between application versions.

## Install

Review the code before installing: hooks run local commands, and installation modifies user-level configuration and links personal skill directories.

```sh
python3 manage.py install
```

The installer backs up affected configuration, adds managed instruction blocks to both agents, configures hooks and Codex's `CLAUDE.md` fallback, and links `~/.claude/skills` to `~/.agents/skills`. Conflicting skill variants stop installation before they are overwritten. Existing native instructions remain intact.

The executable is installed at `~/.local/bin/agent-bridge`; add that directory to your PATH if needed. Runtime files, the database and private backups live in `~/Library/Application Support/AgentBridge`. A launchd job named `local.agent-bridge` imports changes every 20 seconds. Use `--no-launch` to omit the scheduled service.

Review and trust the new Codex hooks through `/hooks`, then start fresh sessions. Sessions already open may retain their previous configuration. No authentication material is installed or supplied by this repository.

## Use

Hooks provide relevant notes at session/turn start and store the final agent response at turn end. A handoff includes the request, reported work and an observed Git snapshot when available. Reported test or deployment results remain agent claims, not independent verification.

```sh
agent-bridge status
agent-bridge recall "database" --project /path/to/repository
agent-bridge recall "previous project" --all-projects
agent-bridge get 42
agent-bridge recall "database" --project /path/to/repository --history
```

To save a durable decision explicitly:

```sh
agent-bridge remember --agent claude --project /path/to/repository \
  --title "Storage" --key "storage" <<'NOTE'
Decision, rationale, completed checks and remaining limitations.
NOTE
```

Use `--agent codex` from Codex, `--agent user` for manual entries, and `--project global` only for genuinely general preferences. Injected guidance currently uses French; stored notes retain their original language.

## Storage and boundaries

Native Markdown memories are read-only sources, including Codex indexes, raw thread memories, rollout summaries, optional memory-extension summaries, and Claude project memories. Entries retain provenance, dates and historical versions. Exact duplicate content shares storage while keeping its sources. Differently worded or contradictory notes remain separate.

Repository worktrees share project identity. Unassigned notes are excluded from ordinary project recall and remain searchable explicitly across projects. Projectless sessions can recognize a uniquely named known repository; ambiguous requests keep their original scope.

The redactor removes common credential patterns, configured sensitive values, email addresses and `<private>` blocks. It cannot recognize every arbitrary secret. Do not put secrets into memory. Native authentication files and Keychain are not imported. Configuration backups can contain original credentials and must remain private.

The bridge has no network transport, but retrieved context is sent to the model provider by the requesting agent. A killed session may not reach its `Stop` hook. Automatic context uses bounded excerpts; `get` retrieves a full stored entry. Requests are capped at 16,000 characters with a truncation notice, individual entries at 200,000 characters, and native source files at 2 MB. Failed imports retain the last valid version and are reported through hooks and `status`.

## Optional configuration synchronization

MCP configuration synchronization is **disabled by default**. To opt in, edit the private `config.json` inside the state directory:

```json
{
  "sync_mcp": true,
  "shared_mcp_names": ["example-server"]
}
```

Only selected servers already configured in both agents are considered. Compatible non-sensitive commands, arguments and environment fields can propagate in either direction. Initial differences remain agent-specific. Concurrent divergent edits are preserved and reported as conflicts. Credentials, plugins, models, permissions and general UI settings are not translated.

`source_scopes`, `project_aliases`, and `claude_project_roots` in that private configuration can refine project mapping. Never commit a populated local configuration.

## Tests and maintenance

```sh
python3 -m unittest -v
python3 manage.py deploy
```

Tests use temporary homes, databases and repositories. `deploy` validates syntax, saves the installed runtime and atomically copies updated source files. It does not reinstall or reapprove hooks.

The original local implementation was additionally exercised in real Claude Code and Codex sessions for two-way recall and project isolation. Private transcripts, session identifiers, installation-specific mappings and memory exports are deliberately absent from this repository. CI exercises the isolated regression suite, not authenticated model sessions.

## Uninstall

```sh
python3 "$HOME/Library/Application Support/AgentBridge/app/manage.py" uninstall
```

This removes the scheduled job, managed hooks and instruction blocks, owned hook trust entries, the added fallback, and the wrapper. It separates the current skill copies without discarding edits made while shared. Other user configuration is retained. Memory and backups remain available; current synchronized MCP values are not reverted.

This early implementation targets local installations. Back up independently before experimenting with a new host or a new native memory format.

## Interface documentation

- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code memory](https://code.claude.com/docs/en/memory)
- [Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## License

MIT. Not affiliated with OpenAI or Anthropic.
