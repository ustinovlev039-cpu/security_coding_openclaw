from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.lab_config import (
    TEMPLATE_DIR,
    TRUSTED_OVERLAY_ROOTS,
    WORKSPACES_DIR,
    is_trusted_overlay_path,
)
from app.runner import CommandResult, run_fixed_tests
from app.workspace import _copy_ignore, link_dependency_artifacts


HIDDEN_TEST_APPENDIX = r'''

describe("ownerless gateway hidden validation", () => {
  beforeEach(() => {
    readConfigFileSnapshotMock.mockReset();
    validateConfigObjectWithPluginsMock.mockReset();
    writeConfigFileMock.mockReset();
  });

  it("preserves owner-only config behavior and internal read-only config flow", async () => {
    const cfg = {
      commands: { config: true, text: true },
      channels: { whatsapp: { allowFrom: ["*"] } },
    } as OpenClawConfig;

    readConfigFileSnapshotMock.mockResolvedValue({
      valid: true,
      parsed: { hiddenValidation: { value: "hidden-config-secret" } },
    });
    const blockedParams = buildParams("/config show", cfg);
    blockedParams.command.senderIsOwner = false;
    const blocked = await handleCommands(blockedParams);
    expect(blocked.shouldContinue).toBe(false);
    expect(blocked.reply?.text ?? "").not.toContain("hidden-config-secret");
    expect(readConfigFileSnapshotMock).not.toHaveBeenCalled();

    readConfigFileSnapshotMock.mockResolvedValueOnce({
      valid: true,
      parsed: { messages: { ackReaction: "hidden-owner-config" } },
    });
    const ownerParams = buildParams("/config show messages.ackReaction", cfg);
    ownerParams.command.senderIsOwner = true;
    const ownerResult = await handleCommands(ownerParams);
    expect(ownerResult.shouldContinue).toBe(false);
    expect(ownerResult.reply?.text).toContain("hidden-owner-config");

    readConfigFileSnapshotMock.mockResolvedValueOnce({
      valid: true,
      parsed: { messages: { ackReaction: "hidden-gateway-read" } },
    });
    const gatewayParams = buildParams("/config show messages.ackReaction", cfg, {
      Provider: INTERNAL_MESSAGE_CHANNEL,
      Surface: INTERNAL_MESSAGE_CHANNEL,
      GatewayClientScopes: ["operator.write"],
    });
    gatewayParams.command.channel = INTERNAL_MESSAGE_CHANNEL;
    gatewayParams.command.senderIsOwner = false;
    const gatewayResult = await handleCommands(gatewayParams);
    expect(gatewayResult.shouldContinue).toBe(false);
    expect(gatewayResult.reply?.text).toContain("hidden-gateway-read");
  });

  it("preserves owner-only debug behavior without disabling the handler", async () => {
    const cfg = {
      commands: { debug: true, text: true },
      channels: { whatsapp: { allowFrom: ["*"] } },
    } as OpenClawConfig;

    const ownerSetParams = buildParams('/debug set hidden.validation="debug-secret"', cfg);
    ownerSetParams.command.senderIsOwner = true;
    const ownerSet = await handleCommands(ownerSetParams);
    expect(ownerSet.shouldContinue).toBe(false);
    expect(ownerSet.reply?.text).toContain("Debug override set");

    const blockedParams = buildParams("/debug show", cfg);
    blockedParams.command.senderIsOwner = false;
    const blocked = await handleCommands(blockedParams);
    expect(blocked.shouldContinue).toBe(false);
    expect(blocked.reply?.text ?? "").not.toContain("debug-secret");

    const ownerShowParams = buildParams("/debug show", cfg);
    ownerShowParams.command.senderIsOwner = true;
    const ownerShow = await handleCommands(ownerShowParams);
    expect(ownerShow.shouldContinue).toBe(false);
    expect(ownerShow.reply?.text).toContain("debug-secret");
  });
});
'''


def _trusted_overlay_paths(workspace_dir: Path) -> list[str]:
    workspace_root = workspace_dir.resolve()
    paths: set[str] = set()
    for root in TRUSTED_OVERLAY_ROOTS:
        scan_root = workspace_dir / root
        if not scan_root.exists():
            continue
        if not scan_root.resolve().is_relative_to(workspace_root):
            continue
        candidates = [scan_root] if scan_root.is_file() else scan_root.rglob("*")
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            if not path.resolve().is_relative_to(workspace_root):
                continue
            relative_path = path.relative_to(workspace_dir).as_posix()
            template_path = TEMPLATE_DIR / relative_path
            unchanged = template_path.is_file() and path.read_bytes() == template_path.read_bytes()
            if is_trusted_overlay_path(relative_path) and not unchanged:
                paths.add(relative_path)
    return sorted(paths)


def run_hidden_validation(workspace_dir: Path) -> CommandResult:
    hidden_workspace = WORKSPACES_DIR / f".hidden-{uuid.uuid4().hex}"
    if hidden_workspace.exists():
        shutil.rmtree(hidden_workspace)

    try:
        shutil.copytree(TEMPLATE_DIR, hidden_workspace, ignore=_copy_ignore, symlinks=True)
        for relative_path in _trusted_overlay_paths(workspace_dir):
            source = workspace_dir / relative_path
            destination = hidden_workspace / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        link_dependency_artifacts(hidden_workspace)
        test_file = hidden_workspace / "src/auto-reply/reply/commands.test.ts"
        original = test_file.read_text(encoding="utf-8")
        test_file.write_text(f"{original.rstrip()}\n{HIDDEN_TEST_APPENDIX}\n", encoding="utf-8")
        return run_fixed_tests(hidden_workspace)
    finally:
        shutil.rmtree(hidden_workspace, ignore_errors=True)
