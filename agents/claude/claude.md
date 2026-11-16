---
name: claude
description: General developer agent running on Claude Code
provider: claude_code
permissionMode: auto
role: developer  # @builtin, fs_*, execute_bash, @cao-mcp-server. For fine-grained control, see docs/tool-restrictions.md
tags:
  - coding
  - implementation
  - python
  - api
  - pytest
  - testing
  - documentation
  - technical-writing
  - docx
capabilities:
  - implement Python APIs and application code
  - write pytest unit and integration tests
  - create and edit technical documentation and DOCX documents
mcpServers:
  cao-mcp-server:
    type: stdio
    command: cao-mcp-server
    args: []
---
