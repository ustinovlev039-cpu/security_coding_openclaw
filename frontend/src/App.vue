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

type Activity = "explorer" | "search" | "brief" | "tests" | "output" | "gateway";
type BottomTab = "problems" | "output" | "tests" | "gateway";
type Overlay = "quick" | "commands" | "shortcuts" | null;
type MenuName = "Workspace" | "Edit" | "View" | "Run" | "Help";
type OpenTab = FileContentResponse & { savedContent: string };

const status = ref<LabStatus>("Vulnerable");
const readableFiles = ref<string[]>([]);
const editableFiles = ref<Set<string>>(new Set());
const pinnedPaths = ref<string[]>([]);
const treeEntries = ref<TreeEntry[]>([]);
const treeChildren = ref<Record<string, TreeEntry[]>>({});
const expandedPaths = ref<Set<string>>(new Set());
const openTabs = ref<OpenTab[]>([]);
const activePath = ref("");
const activity = ref<Activity>("explorer");
const bottomTab = ref<BottomTab>("tests");
const sidebarVisible = ref(true);
const bottomVisible = ref(true);
const bottomHeight = ref(250);
const explorerFilter = ref("");
const saveState = ref<"saved" | "dirty" | "saving" | "error">("saved");
const saveMessage = ref("");
const consoleOutput = ref("Ready. Run tests when you have a fix.");
const lastTest = ref<TestRunSummary | null>(null);
const gatewayRole = ref<GatewayRole>("operator");
const gatewayCommand = ref<GatewayCommand>("config_show");
const gatewayResult = ref<GatewaySimulationResponse | null>(null);
const gatewayRunning = ref(false);
const busy = ref(false);
const overlay = ref<Overlay>(null);
const quickQuery = ref("");
const quickIndex = ref(0);
const commandQuery = ref("");
const commandIndex = ref(0);
const openMenu = ref<MenuName | null>(null);
const cursorLine = ref(1);
const cursorColumn = ref(1);
const selectionLength = ref(0);
const editorEl = ref<HTMLDivElement | null>(null);
const overlayInput = ref<HTMLInputElement | null>(null);
let editor: monaco.editor.IStandaloneCodeEditor | null = null;
let resizing = false;

const topMenuNames: MenuName[] = ["Workspace", "Edit", "View", "Run", "Help"];
const menuActions: Record<MenuName, string[]> = {
  Workspace: ["Open Explorer", "Open Lab Brief", "Reset Workspace"],
  Edit: ["Keyboard Shortcuts"],
  View: ["Toggle Sidebar", "Toggle Bottom Panel", "Open Tests Panel", "Open Gateway Panel"],
  Run: ["Run Tests", "Run Gateway Simulation", "Check Solution"],
  Help: ["Keyboard Shortcuts"],
};
const paletteActions = [
  "Run Tests",
  "Run Gateway Simulation",
  "Check Solution",
  "Reset Workspace",
  "Toggle Sidebar",
  "Toggle Bottom Panel",
  "Open Explorer",
  "Open Lab Brief",
  "Open Tests Panel",
  "Open Gateway Panel",
] as const;

const activeTab = computed(() => openTabs.value.find((tab) => tab.path === activePath.value));
const dirty = computed(() => !!activeTab.value && activeTab.value.content !== activeTab.value.savedContent);
const treeRows = computed(() => flattenTree(treeEntries.value, 0));
const filteredTreeRows = computed(() => {
  const query = explorerFilter.value.trim().toLowerCase();
  if (!query) return treeRows.value;
  return treeRows.value.filter((row) => row.type === "directory" || row.path.toLowerCase().includes(query));
});
const pinnedFiles = computed(() => pinnedPaths.value.filter((path) => readableFiles.value.includes(path)));
const failedTests = computed(() => extractFailedTests(lastTest.value?.output ?? consoleOutput.value));
const activeName = computed(() => basename(activePath.value) || "No file");
const breadcrumbs = computed(() => (activePath.value ? activePath.value.split("/") : []));
const statusClass = computed(() => status.value.toLowerCase().replace(/\s+/g, "-"));
const saveLabel = computed(() => {
  if (saveState.value === "saving") return "Saving...";
  if (saveState.value === "error") return saveMessage.value || "Save failed";
  return dirty.value ? "Unsaved changes" : "Saved";
});
const runnerLabel = computed(() =>
  lastTest.value ? (lastTest.value.ok ? "Tests passed" : "Tests failed") : "Tests not run",
);
const gatewayBadge = computed(() => {
  if (gatewayRunning.value) return "Simulation running...";
  if (!gatewayResult.value) return "Not run";
  if (gatewayResult.value.outcome === "allowed") return "ACCESS GRANTED";
  if (gatewayResult.value.outcome === "blocked") return "ACCESS BLOCKED";
  return "SIMULATION ERROR";
});
const gatewayStatusClass = computed(() => (gatewayRunning.value ? "running" : gatewayResult.value?.outcome ?? "idle"));
const ideStyle = computed(() => ({
  "--bottom-height": bottomVisible.value ? `${bottomHeight.value}px` : "0px",
}));
const quickFiles = computed(() => {
  const query = quickQuery.value.trim().toLowerCase();
  const files = [...readableFiles.value].sort();
  return (query ? files.filter((path) => path.toLowerCase().includes(query)) : files).slice(0, 80);
});
const commandMatches = computed(() => {
  const query = commandQuery.value.trim().toLowerCase();
  return paletteActions.filter((label) => !query || label.toLowerCase().includes(query));
});

function basename(path: string) {
  return path.split("/").pop() ?? path;
}

function isEditable(path: string) {
  return editableFiles.value.has(path);
}

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
  for (const match of output.matchAll(/×\s+(.+?)\s+\d+ms/g)) names.add(match[1].trim());
  return [...names];
}

function updateSaveState() {
  saveState.value = dirty.value ? "dirty" : "saved";
}

function updateCursorState() {
  const position = editor?.getPosition();
  const selection = editor?.getSelection();
  cursorLine.value = position?.lineNumber ?? 1;
  cursorColumn.value = position?.column ?? 1;
  selectionLength.value = selection && editor?.getModel()
    ? editor.getModel()?.getValueLengthInRange(selection) ?? 0
    : 0;
}

function setEditor(tab?: OpenTab) {
  editor?.setValue(tab?.content ?? "");
  editor?.updateOptions({ readOnly: !tab?.editable });
  updateCursorState();
  updateSaveState();
}

async function loadStatus() {
  const response = await api.status();
  status.value = response.status;
  readableFiles.value = response.readable_files;
  editableFiles.value = new Set(response.editable_files);
  lastTest.value = response.last_test;
  if (response.last_test) setConsoleFromTest(response.last_test);
}

async function loadTreeRoot() {
  const response = await api.tree();
  treeEntries.value = response.entries;
  pinnedPaths.value = response.pinned_paths;
  treeChildren.value = {};
  expandedPaths.value = new Set();
  await expandKnownPath("src");
  await expandKnownPath("src/auto-reply");
  await expandKnownPath("src/auto-reply/reply");
  if (!activePath.value) await openFile("src/auto-reply/reply/commands-config.ts");
}

async function expandKnownPath(path: string) {
  try {
    await toggleDirectory(path, true);
  } catch {
    // ponytail: optional convenience expansion; tree still works if a path is absent.
  }
}

async function toggleDirectory(path: string, forceOpen = false) {
  const next = new Set(expandedPaths.value);
  if (next.has(path) && !forceOpen) {
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
  if (!readableFiles.value.includes(path)) return;
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
      if (saveState.value === "error") return;
      status.value = "Tests Running";
      bottomVisible.value = true;
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
      gatewayResult.value = null;
      consoleOutput.value = "Workspace reset to the vulnerable baseline.";
      openTabs.value = [];
      activePath.value = "";
      saveState.value = "saved";
      await loadStatus();
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
  if (busy.value || gatewayRunning.value) return;
  busy.value = true;
  gatewayRunning.value = true;
  bottomVisible.value = true;
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
    gatewayRunning.value = false;
    busy.value = false;
  }
}

function setActivity(next: Activity) {
  activity.value = next;
  if (next === "search") openQuickOpen();
  if (next === "tests") {
    bottomTab.value = "tests";
    bottomVisible.value = true;
  }
  if (next === "output") {
    bottomTab.value = "output";
    bottomVisible.value = true;
  }
  if (next === "gateway") {
    bottomTab.value = "gateway";
    bottomVisible.value = true;
  }
}

function runNamedAction(label: string) {
  openMenu.value = null;
  closeOverlay();
  switch (label) {
    case "Run Tests":
      void runAction("tests");
      break;
    case "Run Gateway Simulation":
      void runGatewaySimulation();
      break;
    case "Check Solution":
      void runAction("check");
      break;
    case "Reset Workspace":
      void runAction("reset");
      break;
    case "Toggle Sidebar":
      sidebarVisible.value = !sidebarVisible.value;
      break;
    case "Toggle Bottom Panel":
      bottomVisible.value = !bottomVisible.value;
      break;
    case "Open Explorer":
      sidebarVisible.value = true;
      activity.value = "explorer";
      break;
    case "Open Lab Brief":
      sidebarVisible.value = true;
      activity.value = "brief";
      break;
    case "Open Tests Panel":
      bottomVisible.value = true;
      bottomTab.value = "tests";
      activity.value = "tests";
      break;
    case "Open Gateway Panel":
      bottomVisible.value = true;
      bottomTab.value = "gateway";
      activity.value = "gateway";
      break;
    case "Keyboard Shortcuts":
      openOverlay("shortcuts");
      break;
  }
}

function openOverlay(kind: Exclude<Overlay, null>) {
  overlay.value = kind;
  openMenu.value = null;
  if (kind === "quick") {
    quickQuery.value = "";
    quickIndex.value = 0;
  }
  if (kind === "commands") {
    commandQuery.value = "";
    commandIndex.value = 0;
  }
  void nextTick(() => overlayInput.value?.focus());
}

function openQuickOpen() {
  openOverlay("quick");
}

function openCommandPalette() {
  openOverlay("commands");
}

function closeOverlay() {
  overlay.value = null;
}

function onQuickKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    closeOverlay();
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    quickIndex.value = Math.min(quickIndex.value + 1, Math.max(quickFiles.value.length - 1, 0));
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    quickIndex.value = Math.max(quickIndex.value - 1, 0);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const selected = quickFiles.value[quickIndex.value];
    if (selected) void openFile(selected);
    closeOverlay();
  }
}

function onCommandKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    closeOverlay();
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    commandIndex.value = Math.min(commandIndex.value + 1, Math.max(commandMatches.value.length - 1, 0));
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    commandIndex.value = Math.max(commandIndex.value - 1, 0);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const selected = commandMatches.value[commandIndex.value];
    if (selected) runNamedAction(selected);
  }
}

function startResize(event: PointerEvent) {
  resizing = true;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}

function onPointerMove(event: PointerEvent) {
  if (!resizing) return;
  const nextHeight = window.innerHeight - event.clientY - 22;
  bottomHeight.value = Math.min(Math.max(nextHeight, 150), 520);
}

function stopResize() {
  resizing = false;
}

function onKeydown(event: KeyboardEvent) {
  const key = event.key.toLowerCase();
  if (event.key === "Escape" && overlay.value) {
    event.preventDefault();
    closeOverlay();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && key === "s") {
    event.preventDefault();
    void saveCurrentFile();
  } else if ((event.ctrlKey || event.metaKey) && event.shiftKey && key === "p") {
    event.preventDefault();
    openCommandPalette();
  } else if ((event.ctrlKey || event.metaKey) && key === "p") {
    event.preventDefault();
    openQuickOpen();
  } else if ((event.ctrlKey || event.metaKey) && key === "j") {
    event.preventDefault();
    bottomVisible.value = !bottomVisible.value;
  } else if ((event.ctrlKey || event.metaKey) && key === "b") {
    event.preventDefault();
    sidebarVisible.value = !sidebarVisible.value;
  } else if (event.key === "F5") {
    event.preventDefault();
    void runAction("tests");
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
    updateSaveState();
  });
  editor.onDidChangeCursorPosition(updateCursorState);
  editor.onDidChangeCursorSelection(updateCursorState);
  window.addEventListener("keydown", onKeydown);
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", stopResize);
  await nextTick();
  await loadStatus();
  await loadTreeRoot();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
  window.removeEventListener("pointermove", onPointerMove);
  window.removeEventListener("pointerup", stopResize);
  editor?.dispose();
});
</script>

<template>
  <main class="ide-shell" :class="{ 'sidebar-hidden': !sidebarVisible, 'bottom-hidden': !bottomVisible }" :style="ideStyle">
    <header class="titlebar">
      <div class="brand">
        <span class="oc-glyph">OC</span>
        <strong>OpenClaw Security Lab</strong>
        <span class="title-separator" />
        <span>Ownerless Gateway</span>
      </div>
      <nav class="menubar" aria-label="Application menu">
        <div v-for="menu in topMenuNames" :key="menu" class="menu">
          <button class="menu-button" @click="openMenu = openMenu === menu ? null : menu">{{ menu }}</button>
          <div v-if="openMenu === menu" class="menu-popover">
            <button v-for="item in menuActions[menu]" :key="item" @click="runNamedAction(item)">
              {{ item }}
            </button>
          </div>
        </div>
      </nav>
      <div class="chrome-actions">
        <span class="status-pill" :class="statusClass">{{ status }}</span>
        <span class="save-indicator" :class="saveState">{{ saveLabel }}</span>
        <button :disabled="busy" @click="runAction('tests')">Run Tests</button>
        <button :disabled="busy" @click="runAction('reset')">Reset</button>
        <button class="primary" :disabled="busy" @click="runAction('check')">Check</button>
      </div>
    </header>

    <div class="workbench">
      <nav class="activity-bar" aria-label="Views">
        <button :class="{ active: activity === 'explorer' }" title="Explorer" aria-label="Explorer" @click="setActivity('explorer')">
          <svg viewBox="0 0 24 24"><path d="M4 6h6l2 2h8v11H4z" /></svg>
        </button>
        <button :class="{ active: activity === 'search' }" title="Search / Quick Open" aria-label="Search / Quick Open" @click="setActivity('search')">
          <svg viewBox="0 0 24 24"><path d="M10 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm4 9 5 5" /></svg>
        </button>
        <button :class="{ active: activity === 'brief' }" title="Lab Brief" aria-label="Lab Brief" @click="setActivity('brief')">
          <svg viewBox="0 0 24 24"><path d="M6 4h12v16H6zM9 8h6M9 12h6M9 16h4" /></svg>
        </button>
        <button :class="{ active: activity === 'tests' }" title="Tests" aria-label="Tests" @click="setActivity('tests')">
          <svg viewBox="0 0 24 24"><path d="M5 12h4l2 4 4-8 2 4h2" /></svg>
        </button>
        <button :class="{ active: activity === 'output' }" title="Output" aria-label="Output" @click="setActivity('output')">
          <svg viewBox="0 0 24 24"><path d="M5 7h14M5 12h10M5 17h12" /></svg>
        </button>
        <button :class="{ active: activity === 'gateway' }" title="Gateway" aria-label="Gateway" @click="setActivity('gateway')">
          <svg viewBox="0 0 24 24"><path d="M12 4 20 12 12 20 4 12zM12 8v8M8 12h8" /></svg>
        </button>
      </nav>

      <aside class="sidebar">
        <template v-if="activity === 'explorer'">
          <div class="side-title">Explorer</div>
          <input v-model="explorerFilter" class="side-filter" type="search" placeholder="Filter opened tree" />

          <div class="tree-section">OPEN EDITORS</div>
          <button
            v-for="tab in openTabs"
            :key="`open:${tab.path}`"
            class="tree-row compact"
            :class="{ selected: tab.path === activePath, readonly: !tab.editable }"
            :title="tab.path"
            @click="activateTab(tab.path)"
          >
            <span class="file-icon">TS</span>
            <span class="file-label">{{ basename(tab.path) }}</span>
            <span v-if="tab.content !== tab.savedContent" class="dirty-dot" />
          </button>
          <p v-if="!openTabs.length" class="empty-note">No open editors</p>

          <div class="tree-section">PINNED</div>
          <button
            v-for="path in pinnedFiles"
            :key="`pin:${path}`"
            class="tree-row compact"
            :class="{ selected: path === activePath, readonly: !isEditable(path) }"
            :title="path"
            @click="openFile(path)"
          >
            <span class="file-icon">TS</span>
            <span class="file-label">{{ basename(path) }}</span>
            <span class="file-state">{{ isEditable(path) ? "edit" : "lock" }}</span>
          </button>

          <div class="tree-section">OPENCLAW-TRAINING-FORK</div>
          <button
            v-for="row in filteredTreeRows"
            :key="`${row.type}:${row.path}`"
            class="tree-row"
            :class="{ selected: row.path === activePath, readonly: row.type === 'file' && !row.editable, folder: row.type === 'directory' }"
            :style="{ paddingLeft: `${8 + row.depth * 14}px` }"
            :title="row.path"
            @click="handleTreeClick(row)"
          >
            <span class="twisty">{{ row.type === "directory" ? (expandedPaths.has(row.path) ? "⌄" : "›") : "" }}</span>
            <span v-if="row.type === 'file'" class="file-icon">TS</span>
            <span class="file-label">{{ row.name }}</span>
            <span v-if="row.type === 'file'" class="file-state">{{ row.editable ? "edit" : "lock" }}</span>
          </button>
        </template>

        <template v-else-if="activity === 'search'">
          <div class="side-title">Search / Quick Open</div>
          <p class="side-copy">Use Ctrl+P / Cmd+P to open authorized files from the lab manifest.</p>
          <button class="side-command" @click="openQuickOpen">Open Quick Open</button>
        </template>

        <template v-else-if="activity === 'brief'">
          <div class="side-title">Lab Brief</div>
          <section class="brief-block">
            <h3>Scenario</h3>
            <p>OpenClaw Gateway distinguishes command authorization from ownership. Authorized operators may use normal commands, but <code>/config</code> and <code>/debug</code> must remain owner-only.</p>
          </section>
          <section class="brief-block">
            <h3>Objective</h3>
            <p>Fix the access-control regression without breaking allowed owner behavior or internal read-only config flow.</p>
          </section>
          <section class="brief-block">
            <h3>Security invariant</h3>
            <p>Authorized does not imply owner.</p>
          </section>
          <section class="brief-block">
            <h3>Editable scope</h3>
            <p><code>commands-config.ts</code> and <code>command-gates.ts</code>.</p>
          </section>
          <section class="brief-block">
            <h3>Success conditions</h3>
            <p>Owners keep access; non-owner protected command responses are blocked; tests and hidden validation pass.</p>
          </section>
        </template>

        <template v-else>
          <div class="side-title">{{ activity === "gateway" ? "Gateway" : activity === "tests" ? "Tests" : "Output" }}</div>
          <p class="side-copy">{{ activity === "gateway" ? gatewayBadge : runnerLabel }}</p>
          <p v-if="lastTest" class="side-copy">exit {{ lastTest.exit_code }} · {{ lastTest.duration_ms }}ms</p>
          <ul v-if="failedTests.length" class="failed-mini">
            <li v-for="name in failedTests" :key="name">{{ name }}</li>
          </ul>
        </template>
      </aside>

      <section class="editor-area">
        <div class="tabs">
          <button
            v-for="tab in openTabs"
            :key="tab.path"
            :class="{ active: tab.path === activePath }"
            :title="tab.path"
            @click="activateTab(tab.path)"
          >
            <span class="file-icon">TS</span>
            <span class="tab-name">{{ basename(tab.path) }}</span>
            <span v-if="tab.content !== tab.savedContent" class="dirty-dot" />
            <span class="close-tab" title="Close" @click.stop="closeTab(tab.path)">×</span>
          </button>
        </div>
        <div class="breadcrumb">
          <span v-for="(segment, index) in breadcrumbs" :key="`${segment}:${index}`" class="crumb">
            {{ segment }}<span v-if="index < breadcrumbs.length - 1" class="crumb-sep">›</span>
          </span>
          <span v-if="activeTab && !activeTab.editable" class="readonly-badge">READ ONLY</span>
        </div>
        <div ref="editorEl" class="editor-host" />
      </section>
    </div>

    <section class="bottom-panel">
      <div class="resize-handle" title="Resize panel" @pointerdown="startResize" />
      <div class="bottom-tabs">
        <button :class="{ active: bottomTab === 'problems' }" @click="bottomTab = 'problems'">PROBLEMS</button>
        <button :class="{ active: bottomTab === 'output' }" @click="bottomTab = 'output'">OUTPUT</button>
        <button :class="{ active: bottomTab === 'tests' }" @click="bottomTab = 'tests'">TESTS</button>
        <button :class="{ active: bottomTab === 'gateway' }" @click="bottomTab = 'gateway'">GATEWAY</button>
        <button class="panel-toggle" @click="bottomVisible = !bottomVisible">{{ bottomVisible ? "Collapse" : "Expand" }}</button>
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
                <select v-model="gatewayRole" :disabled="gatewayRunning">
                  <option value="owner">owner</option>
                  <option value="operator">operator</option>
                </select>
              </label>
              <div class="gateway-command-buttons" aria-label="Fixed gateway command">
                <button :disabled="gatewayRunning" :class="{ active: gatewayCommand === 'config_show' }" @click="gatewayCommand = 'config_show'">
                  /config show
                </button>
                <button :disabled="gatewayRunning" :class="{ active: gatewayCommand === 'debug_show' }" @click="gatewayCommand = 'debug_show'">
                  /debug show
                </button>
              </div>
              <button class="primary" :disabled="busy || gatewayRunning" @click="runGatewaySimulation">
                {{ gatewayRunning ? "Simulation running..." : "Run Gateway Simulation" }}
              </button>
              <span class="gateway-badge" :class="gatewayStatusClass">{{ gatewayBadge }}</span>
            </div>
            <div v-if="gatewayResult" class="gateway-result">
              <span>Role: {{ gatewayResult.role }}</span>
              <span>Command: {{ gatewayResult.display_command }}</span>
              <span>Outcome: {{ gatewayResult.outcome }}</span>
              <span>Duration: {{ gatewayResult.duration_ms }}ms</span>
              <span>{{ gatewayResult.summary }}</span>
              <pre>{{ gatewayResult.safe_output }}</pre>
            </div>
            <p v-else class="empty-note">Fixed scenarios only. No custom command input is available.</p>
          </div>
        </template>
        <pre v-else-if="bottomTab === 'output'">{{ consoleOutput }}</pre>
        <template v-else>
          <ul v-if="failedTests.length" class="failed-list">
            <li v-for="name in failedTests" :key="name">{{ name }}</li>
          </ul>
          <p v-else>Static analysis is not enabled for this MVP. Problems are limited to parsed failed test names.</p>
        </template>
      </div>
    </section>

    <footer class="statusbar">
      <div class="status-left">
        <span>{{ activeName }}</span>
        <span>openclaw-training-fork</span>
        <span>{{ activeTab?.editable ? "Editable" : "Read-only" }}</span>
      </div>
      <div class="status-right">
        <span>Ln {{ cursorLine }}, Col {{ cursorColumn }}</span>
        <span v-if="selectionLength">Sel {{ selectionLength }}</span>
        <span>Spaces: 2</span>
        <span>UTF-8</span>
        <span>TypeScript</span>
        <span>{{ runnerLabel }}</span>
        <span v-if="gatewayResult">Gateway: {{ gatewayResult.outcome }}</span>
      </div>
    </footer>

    <div v-if="overlay" class="overlay" @click.self="closeOverlay">
      <div class="overlay-box">
        <template v-if="overlay === 'quick'">
          <div class="overlay-title">Quick Open</div>
          <input
            ref="overlayInput"
            v-model="quickQuery"
            class="overlay-input"
            placeholder="Type a file name from the allowed manifest"
            @input="quickIndex = 0"
            @keydown.stop="onQuickKeydown"
          />
          <div class="overlay-list">
            <button
              v-for="(path, index) in quickFiles"
              :key="path"
              :class="{ selected: index === quickIndex }"
              @click="openFile(path); closeOverlay()"
            >
              <span class="file-icon">TS</span>
              <span>{{ basename(path) }}</span>
              <small>{{ path }}</small>
            </button>
          </div>
        </template>

        <template v-else-if="overlay === 'commands'">
          <div class="overlay-title">Command Palette</div>
          <input
            ref="overlayInput"
            v-model="commandQuery"
            class="overlay-input"
            placeholder="Search fixed safe actions"
            @input="commandIndex = 0"
            @keydown.stop="onCommandKeydown"
          />
          <div class="overlay-list">
            <button
              v-for="(label, index) in commandMatches"
              :key="label"
              :class="{ selected: index === commandIndex }"
              @click="runNamedAction(label)"
            >
              <span>{{ label }}</span>
            </button>
          </div>
        </template>

        <template v-else>
          <div class="overlay-title">Keyboard Shortcuts</div>
          <dl class="shortcuts">
            <dt>Ctrl/Cmd+S</dt><dd>Save editable file</dd>
            <dt>Ctrl/Cmd+P</dt><dd>Quick Open</dd>
            <dt>Ctrl/Cmd+Shift+P</dt><dd>Command Palette</dd>
            <dt>F5</dt><dd>Run Tests</dd>
            <dt>Ctrl/Cmd+J</dt><dd>Toggle Bottom Panel</dd>
            <dt>Ctrl/Cmd+B</dt><dd>Toggle Sidebar</dd>
            <dt>Escape</dt><dd>Close overlay</dd>
          </dl>
        </template>
      </div>
    </div>
  </main>
</template>
