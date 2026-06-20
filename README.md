# OpenClaw: Ownerless Gateway

Local MVP for a Broken Access Control / Security Coding lab around OpenClaw owner-only commands.

This is a single-user local MVP. The default workspace is `.lab/workspaces/default` and is not suitable for concurrent multi-user deployment.

The backend already keeps the workspace identifier behind `LAB_WORKSPACE_ID` / `WORKSPACE_ID`, so a later multi-user version can replace the default ID with a session-specific workspace without changing the challenge source layout.

