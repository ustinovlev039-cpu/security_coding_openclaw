import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

type Role = "owner" | "operator";
type CommandId = "config_show" | "debug_show";
type Outcome = "allowed" | "blocked" | "error";

const RESULT_PREFIX = "__OPENCLAW_GATEWAY_SIMULATION_RESULT__";
const trustedWrite = process.stdout.write.bind(process.stdout);
const trustedExit = process.exit.bind(process);
const trustedStringify = JSON.stringify.bind(JSON);
const COMMANDS: Record<CommandId, string> = {
  config_show: "/config show",
  debug_show: "/debug show",
};

function clean(value: string, replacements: string[]): string {
  let output = value.replace(/\u001b\[[0-9;]*m/g, "");
  for (const replacement of replacements.filter(Boolean)) {
    output = output.split(replacement).join("[redacted-path]");
  }
  return output.slice(0, 2_000);
}

function isProtectedCommandOutput(command: CommandId, text: string): boolean {
  if (command === "config_show") {
    return /^⚙️ Config(?:\s|\()/u.test(text);
  }
  return text.includes("⚙️ Debug overrides");
}

function finish(result: {
  ok: boolean;
  role: Role;
  command: CommandId;
  display_command: string;
  outcome: Outcome;
  summary: string;
  safe_output: string;
}, exitCode = 0): never {
  trustedWrite(`${RESULT_PREFIX}${trustedStringify(result)}\n`);
  trustedExit(exitCode);
}

async function main() {
  const role = process.argv[2] as Role;
  const command = process.argv[3] as CommandId;
  if (!["owner", "operator"].includes(role) || !["config_show", "debug_show"].includes(command)) {
    finish({
      ok: false,
      role: "operator",
      command: "config_show",
      display_command: "/config show",
      outcome: "error",
      summary: "Gateway simulation received an invalid fixed scenario.",
      safe_output: "Invalid simulation request.",
    }, 1);
  }

  const workspace = process.env.OPENCLAW_SIM_WORKSPACE ?? process.cwd();
  const tmp = process.env.TMPDIR ?? os.tmpdir();
  const configPath = path.join(tmp, "openclaw-sim-config.json");
  const stateDir = path.join(tmp, "state");
  const displayCommand = COMMANDS[command];
  const replacements = [workspace, tmp, process.env.HOME ?? ""];

  await fs.mkdir(stateDir, { recursive: true });
  await fs.writeFile(
    configPath,
    JSON.stringify(
      {
        agents: { defaults: { model: "anthropic/claude-opus-4-6" } },
      },
      null,
      2,
    ),
    "utf-8",
  );

  process.env.OPENCLAW_CONFIG_PATH = configPath;
  process.env.OPENCLAW_STATE_DIR = stateDir;
  process.env.OPENCLAW_HOME = stateDir;

  // Keep trusted driver output parseable even if imported modules log during import.
  console.log = () => undefined;
  console.error = () => undefined;
  console.warn = () => undefined;

  try {
    const [{ buildCommandTestParams }, { handleCommands }] = await Promise.all([
      import(pathToFileURL(path.join(workspace, "src/auto-reply/reply/commands.test-harness.ts")).href),
      import(pathToFileURL(path.join(workspace, "src/auto-reply/reply/commands.ts")).href),
    ]);
    const cfg = {
      commands: { config: true, debug: true, text: true },
      channels: { whatsapp: { allowFrom: ["*"] } },
    };
    const params = buildCommandTestParams(
      displayCommand,
      cfg,
      { SenderId: role === "owner" ? "owner-1" : "operator-1" },
      { workspaceDir: tmp },
    );
    params.command.senderIsOwner = role === "owner";
    params.command.isAuthorizedSender = true;

    const result = await handleCommands(params);
    const text = result.reply?.text ? clean(String(result.reply.text), replacements) : "";
    const outcome: Outcome = isProtectedCommandOutput(command, text) ? "allowed" : "blocked";
    finish({
      ok: true,
      role,
      command,
      display_command: displayCommand,
      outcome,
      summary:
        outcome === "allowed"
          ? "Gateway returned the protected command response."
          : "Gateway blocked or withheld the protected command response.",
      safe_output: text || "No reply was returned.",
    });
  } catch (error) {
    finish({
      ok: false,
      role,
      command,
      display_command: displayCommand,
      outcome: "error",
      summary: "Gateway simulation failed before a command outcome was produced.",
      safe_output: clean(error instanceof Error ? error.message : String(error), replacements),
    });
  }
}

main().catch((error) => {
  finish({
    ok: false,
    role: "operator",
    command: "config_show",
    display_command: "/config show",
    outcome: "error",
    summary: "Gateway simulation failed before request validation completed.",
    safe_output: error instanceof Error ? error.message.slice(0, 2_000) : String(error).slice(0, 2_000),
  }, 1);
});
