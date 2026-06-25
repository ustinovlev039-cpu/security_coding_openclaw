<script setup lang="ts">
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "./api";
import type {
  FileContentResponse,
  GatewayCommand,
  GatewayRole,
  GatewaySimulationResponse,
  LabStatus,
  TestRunSummary,
  TreeEntry,
  TreeRow,
} from "./types";

type Activity = "explorer" | "brief" | "tests" | "output";
type BottomTab = "tests" | "output" | "problems" | "gateway";
type OpenTab = FileContentResponse & { savedContent: string };

const status = ref<LabStatus>("Vulnerable");
const treeEntries = ref<TreeEntry[]>([]);
const treeChildren = ref<Record<string, TreeEntry[]>>({});
const expandedPaths = ref<Set<string>>(new Set());
const openTabs = ref<OpenTab[]>([]);
const activePath = ref("");
const activity = ref<Activity>("explorer");
const bottomTab = ref<BottomTab>("tests");
const saveState = ref<"saved" | "dirty" | "saving" | "error">("saved");
const saveMessage = ref("");
const consoleOutput = ref("Ready. Run tests when you have a fix.");
const lastTest = ref<TestRunSummary | null>(null);
const gatewayRole = ref<GatewayRole>("operator");
const gatewayCommand = ref<GatewayCommand>("config_show");
const gatewayResult = ref<GatewaySimulationResponse | null>(null);
const busy = ref(false);
const editorEl = ref<HTMLDivElement | null>(null);
let editor: monaco.editor.IStandaloneCodeEditor | null = null;

const activeTab = computed(() => openTabs.value.find((tab) => tab.path === activePath.value));
const dirty = computed(() => !!activeTab.value && activeTab.value.content !== activeTab.value.savedContent);
const treeRows = computed(() => flattenTree(treeEntries.value, 0));
const failedTests = computed(() => extractFailedTests(lastTest.value?.output ?? consoleOutput.value));
const statusClass = computed(() => status.value.toLowerCase().replace(/\s+/g, "-"));
const saveLabel = computed(() => {
  if (saveState.value === "saving") return "Saving...";
  if (saveState.value === "error") return saveMessage.value || "Save failed";
  return dirty.value ? "Unsaved changes" : "Saved";
});
const runnerLabel = computed(() => lastTest.value ? (lastTest.value.ok ? "Tests passed" : "Tests failed") : "Tests not run");
const gatewayBadge = computed(() => {
  if (!gatewayResult.value) return "Not run";
  if (gatewayResult.value.outcome === "allowed") return "ACCESS GRANTED";
  if (gatewayResult.value.outcome === "blocked") return "ACCESS BLOCKED";
  return "SIMULATION ERROR";
});
const gatewayStatusClass = computed(() => gatewayResult.value?.outcome ?? "idle");

function flattenTree(entries: TreeEntry[], depth: number): TreeRow[] {
  return entries.flatMap((entry) => [
    { ...entry, depth },
    ...(entry.type === "directory" && expandedPaths.value.has(entry.path)
      ? flattenTree(treeChildren.value[entry.path] ?? [], depth + 1)
      : []),
  ]);
}

function extractFailedTests(output: string): string[] {
  const names = new Set<string>();
  for (const match of output.matchAll(/FAIL\s+.*?>\s+(.+)/g)) names.add(match[1].trim());
  return [...names];
}

function setEditor(tab?: OpenTab) {
  editor?.setValue(tab?.content ?? "");
  editor?.updateOptions({ readOnly: !tab?.editable });
}

async function loadStatus() {
  const response = await api.status();
  status.value = response.status;
  lastTest.value = response.last_test;
  if (response.last_test) setConsoleFromTest(response.last_test);
}

async function loadTreeRoot() {
  const response = await api.tree();
  treeEntries.value = response.entries;
  treeChildren.value = {};
  expandedPaths.value = new Set();
  const firstFile = response.entries.find((entry) => entry.type === "file");
  if (firstFile && !activePath.value) await openFile(firstFile.path);
}

async function toggleDirectory(path: string) {
  const next = new Set(expandedPaths.value);
  if (next.has(path)) {
    next.delete(path);
    expandedPaths.value = next;
    return;
  }
  if (!treeChildren.value[path]) {
    treeChildren.value = { ...treeChildren.value, [path]: (await api.tree(path)).entries };
  }
  next.add(path);
  expandedPaths.value = next;
}

async function handleTreeClick(row: TreeRow) {
  if (row.type === "directory") return toggleDirectory(row.path);
  return openFile(row.path);
}

async function openFile(path: string) {
  const existing = openTabs.value.find((tab) => tab.path === path);
  if (existing) {
    activePath.value = path;
    setEditor(existing);
    return;
  }
  const file = await api.file(path);
  const tab = { ...file, savedContent: file.content };
  openTabs.value = [...openTabs.value, tab];
  activePath.value = path;
  setEditor(tab);
  saveState.value = "saved";
}

function activateTab(path: string) {
  activePath.value = path;
  setEditor(activeTab.value);
}

function closeTab(path: string) {
  const index = openTabs.value.findIndex((tab) => tab.path === path);
  openTabs.value = openTabs.value.filter((tab) => tab.path !== path);
  if (activePath.value === path) {
    activePath.value = openTabs.value[Math.max(0, index - 1)]?.path ?? "";
    setEditor(activeTab.value);
  }
}

async function saveCurrentFile() {
  const tab = activeTab.value;
  if (!tab || !tab.editable || tab.content === tab.savedContent) return;
  saveState.value = "saving";
  try {
    await api.saveFile(tab.path, tab.content);
    tab.savedContent = tab.content;
    saveState.value = "saved";
    saveMessage.value = "";
    status.value = "Vulnerable";
  } catch (error) {
    saveState.value = "error";
    saveMessage.value = error instanceof Error ? error.message : "Save failed";
  }
}

function setConsoleFromTest(result: TestRunSummary) {
  consoleOutput.value = result.output || "(no output)";
}

function displayGatewayCommand(command: GatewayCommand) {
  return command === "config_show" ? "/config show" : "/debug show";
}

async function runAction(action: "tests" | "reset" | "check") {
  if (busy.value) return;
  busy.value = true;
  try {
    if (action !== "reset") {
      await saveCurrentFile();
      status.value = "Tests Running";
      bottomTab.value = "tests";
    }
    if (action === "tests") {
      const response = await api.runTests();
      status.value = response.status;
      lastTest.value = response.result;
      setConsoleFromTest(response.result);
    } else if (action === "check") {
      const response = await api.checkSolution();
      status.value = response.status;
      lastTest.value = response.visible_tests;
      setConsoleFromTest(response.visible_tests);
      consoleOutput.value += `\n\nHidden validation: ${response.hidden_validation}`;
    } else {
      const response = await api.reset();
      status.value = response.status;
      lastTest.value = null;
      consoleOutput.value = "Workspace reset to the vulnerable baseline.";
      openTabs.value = [];
      activePath.value = "";
      saveState.value = "saved";
      await loadTreeRoot();
    }
  } catch (error) {
    status.value = "Tests Failed";
    consoleOutput.value = error instanceof Error ? error.message : String(error);
  } finally {
    busy.value = false;
  }
}

async function runGatewaySimulation() {
  if (busy.value) return;
  busy.value = true;
  bottomTab.value = "gateway";
  try {
    await saveCurrentFile();
    if (saveState.value === "error") return;
    gatewayResult.value = await api.gatewaySimulate({
      role: gatewayRole.value,
      command: gatewayCommand.value,
    });
    consoleOutput.value = [
      `Gateway simulation: ${gatewayResult.value.role} ${gatewayResult.value.display_command}`,
      `Outcome: ${gatewayResult.value.outcome}`,
      gatewayResult.value.safe_output,
    ].join("\n");
  } catch (error) {
    gatewayResult.value = {
      ok: false,
      role: gatewayRole.value,
      command: gatewayCommand.value,
      display_command: displayGatewayCommand(gatewayCommand.value),
      outcome: "error",
      summary: "Gateway simulation request failed.",
      safe_output: error instanceof Error ? error.message : String(error),
      duration_ms: 0,
    };
  } finally {
    busy.value = false;
  }
}

function setActivity(next: Activity) {
  activity.value = next;
  if (next === "tests") bottomTab.value = "tests";
  if (next === "output") bottomTab.value = "output";
}

function onKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void saveCurrentFile();
  }
}

onMounted(async () => {
  editor = monaco.editor.create(editorEl.value as HTMLDivElement, {
    value: "",
    language: "typescript",
    theme: "vs",
    automaticLayout: true,
    minimap: { enabled: false },
    fontFamily: "'JetBrains Mono', 'SFMono-Regular', Consolas, monospace",
    fontSize: 14,
    lineHeight: 21,
    scrollBeyondLastLine: false,
    wordWrap: "on",
    tabSize: 2,
  });
  editor.onDidChangeModelContent(() => {
    const tab = activeTab.value;
    if (!tab) return;
    tab.content = editor?.getValue() ?? "";
    saveState.value = tab.content === tab.savedContent ? "saved" : "dirty";
  });
  window.addEventListener("keydown", onKeydown);
  await nextTick();
  await loadStatus();
  await loadTreeRoot();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
  editor?.dispose();
});
</script>

<template>
  <main class="ide-shell">
    <header class="topbar">
      <div class="top-title">
        <strong>OpenClaw: Ownerless Gateway</strong>
        <span class="status-pill" :class="statusClass">{{ status }}</span>
      </div>
      <div class="top-actions">
        <span class="save-indicator" :class="saveState">{{ saveLabel }}</span>
        <button :disabled="busy" @click="runGatewaySimulation">Run Gateway Simulation</button>
        <button :disabled="busy" @click="runAction('tests')">Run Tests</button>
        <button :disabled="busy" @click="runAction('reset')">Reset</button>
        <button class="primary" :disabled="busy" @click="runAction('check')">Check Solution</button>
      </div>
    </header>

    <div class="ide-main">
      <nav class="activity-bar" aria-label="Views">
        <button :class="{ active: activity === 'explorer' }" title="Explorer" @click="setActivity('explorer')">E</button>
        <button :class="{ active: activity === 'brief' }" title="Lab Brief" @click="setActivity('brief')">B</button>
        <button :class="{ active: activity === 'tests' }" title="Tests" @click="setActivity('tests')">T</button>
        <button :class="{ active: activity === 'output' }" title="Output" @click="setActivity('output')">O</button>
      </nav>

      <aside class="sidebar">
        <template v-if="activity === 'explorer'">
          <h2>Explorer</h2>
          <div class="tree-section">Pinned</div>
          <button
            v-for="row in treeRows.filter((entry) => entry.pinned)"
            :key="`pin:${row.path}`"
            class="tree-row"
            :class="{ selected: row.path === activePath, readonly: !row.editable }"
            @click="openFile(row.path)"
          >
            <span class="file-icon">TS</span>
            <span class="file-label">{{ row.name }}</span>
            <span class="file-state">{{ row.editable ? "edit" : "read" }}</span>
          </button>
          <div class="tree-section">Source</div>
          <button
            v-for="row in treeRows"
            :key="`${row.type}:${row.path}`"
            class="tree-row"
            :class="{ selected: row.path === activePath, readonly: row.type === 'file' && !row.editable, folder: row.type === 'directory' }"
            :style="{ paddingLeft: `${8 + row.depth * 14}px` }"
            @click="handleTreeClick(row)"
          >
            <span class="file-icon">{{ row.type === "directory" ? (expandedPaths.has(row.path) ? "v" : ">") : "TS" }}</span>
            <span class="file-label">{{ row.path }}</span>
            <span v-if="row.type === 'file'" class="file-state">{{ row.editable ? "edit" : "read" }}</span>
          </button>
        </template>

        <template v-else-if="activity === 'brief'">
          <h2>Lab Brief</h2>
          <p>OpenClaw Gateway distinguishes command authorization from ownership. Authorized operators may use normal commands, but <code>/config</code> and <code>/debug</code> must remain owner-only.</p>
          <ul>
            <li>Block non-owner <code>/config show</code>.</li>
            <li>Block non-owner <code>/debug show</code>.</li>
            <li>Keep owner behavior working.</li>
            <li>Keep internal read-only config flow.</li>
          </ul>
        </template>

        <template v-else>
          <h2>{{ activity === "tests" ? "Tests" : "Output" }}</h2>
          <p>{{ runnerLabel }}</p>
          <p v-if="lastTest">exit {{ lastTest.exit_code }} · {{ lastTest.duration_ms }}ms</p>
          <ul v-if="failedTests.length">
            <li v-for="name in failedTests" :key="name">{{ name }}</li>
          </ul>
        </template>
      </aside>

      <section class="editor-area">
        <div class="tabs">
          <button
            v-for="tab in openTabs"
            :key="tab.path"
            :class="{ active: tab.path === activePath, dirty: tab.content !== tab.savedContent }"
            @click="activateTab(tab.path)"
          >
            {{ tab.path.split("/").at(-1) }}
            <span v-if="tab.content !== tab.savedContent">*</span>
            <span class="close-tab" @click.stop="closeTab(tab.path)">x</span>
          </button>
        </div>
        <div class="breadcrumb">
          <span>{{ activePath || "No file open" }}</span>
          <span v-if="activeTab && !activeTab.editable" class="readonly-badge">READ ONLY</span>
        </div>
        <div ref="editorEl" class="editor-host" />
      </section>
    </div>

    <section class="bottom-panel">
      <div class="bottom-tabs">
        <button :class="{ active: bottomTab === 'tests' }" @click="bottomTab = 'tests'">TESTS</button>
        <button :class="{ active: bottomTab === 'gateway' }" @click="bottomTab = 'gateway'">GATEWAY</button>
        <button :class="{ active: bottomTab === 'output' }" @click="bottomTab = 'output'">OUTPUT</button>
        <button :class="{ active: bottomTab === 'problems' }" @click="bottomTab = 'problems'">PROBLEMS</button>
      </div>
      <div class="panel-body">
        <template v-if="bottomTab === 'tests'">
          <div class="test-summary">
            <strong>{{ runnerLabel }}</strong>
            <span v-if="lastTest">exit {{ lastTest.exit_code }} · {{ lastTest.duration_ms }}ms</span>
          </div>
          <ul v-if="failedTests.length" class="failed-list">
            <li v-for="name in failedTests" :key="name">{{ name }}</li>
          </ul>
          <p v-else>No failed tests parsed from output.</p>
        </template>
        <template v-else-if="bottomTab === 'gateway'">
          <div class="gateway-panel">
            <div class="gateway-controls">
              <label>
                Role
                <select v-model="gatewayRole">
                  <option value="owner">owner</option>
                  <option value="operator">operator</option>
                </select>
              </label>
              <div class="gateway-command-buttons" aria-label="Fixed gateway command">
                <button
                  :class="{ active: gatewayCommand === 'config_show' }"
                  @click="gatewayCommand = 'config_show'"
                >
                  /config show
                </button>
                <button
                  :class="{ active: gatewayCommand === 'debug_show' }"
                  @click="gatewayCommand = 'debug_show'"
                >
                  /debug show
                </button>
              </div>
              <button class="primary" :disabled="busy" @click="runGatewaySimulation">
                Run Gateway Simulation
              </button>
              <span class="gateway-badge" :class="gatewayStatusClass">{{ gatewayBadge }}</span>
            </div>
            <p class="gateway-note">Uses the currently saved workspace code. No free-form command input is available.</p>
            <div v-if="gatewayResult" class="gateway-result">
              <div><strong>Role:</strong> {{ gatewayResult.role }}</div>
              <div><strong>Command:</strong> {{ gatewayResult.display_command }}</div>
              <div><strong>Outcome:</strong> {{ gatewayResult.outcome }}</div>
              <div><strong>Duration:</strong> {{ gatewayResult.duration_ms }}ms</div>
              <div><strong>Explanation:</strong> {{ gatewayResult.summary }}</div>
              <pre>{{ gatewayResult.safe_output }}</pre>
            </div>
            <p v-else>Select a role and fixed command, then run the simulation.</p>
          </div>
        </template>
        <pre v-else-if="bottomTab === 'output'">{{ consoleOutput }}</pre>
        <template v-else>
          <ul v-if="failedTests.length" class="failed-list">
            <li v-for="name in failedTests" :key="name">{{ name }}</li>
          </ul>
          <p v-else>Static analysis is not enabled for this MVP.</p>
        </template>
      </div>
    </section>

    <footer class="statusbar">
      <span>{{ activePath || "No file" }}</span>
      <span>TypeScript</span>
      <span>{{ activeTab?.editable ? "Editable" : "Read-only" }}</span>
      <span>OpenClaw Ownerless Gateway</span>
      <span>{{ gatewayResult ? `Gateway: ${gatewayResult.outcome}` : runnerLabel }}</span>
    </footer>
  </main>
</template>
