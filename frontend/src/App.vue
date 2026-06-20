<script setup lang="ts">
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "./api";
import type { FileEntry, LabStatus, TestRunSummary } from "./types";

const status = ref<LabStatus>("Vulnerable");
const files = ref<FileEntry[]>([]);
const selectedPath = ref("");
const content = ref("");
const savedContent = ref("");
const currentEditable = ref(true);
const consoleOutput = ref("Ready. Run the visible regression tests when you have a fix.");
const lastTest = ref<TestRunSummary | null>(null);
const busy = ref(false);
const editorEl = ref<HTMLDivElement | null>(null);
let editor: monaco.editor.IStandaloneCodeEditor | null = null;

const dirty = computed(() => content.value !== savedContent.value);
const editableFileCount = computed(() => files.value.filter((file) => file.editable).length);
const selectedFileName = computed(() => selectedPath.value.split("/").at(-1) ?? "No file");

const statusClass = computed(() =>
  status.value.toLowerCase().replace(/\s+/g, "-"),
);

function setConsoleFromTest(result: TestRunSummary) {
  const heading = `$ ${result.command}\nexit=${result.exit_code} duration=${result.duration_ms}ms`;
  consoleOutput.value = `${heading}\n\n${result.output || "(no output)"}`;
}

async function loadStatus() {
  const response = await api.status();
  status.value = response.status;
  lastTest.value = response.last_test;
  if (response.last_test) {
    setConsoleFromTest(response.last_test);
  }
}

async function loadFiles() {
  const response = await api.files();
  files.value = response.files;
  if (!selectedPath.value && response.files.length > 0) {
    await openFile(response.files[0].path);
  }
}

async function openFile(path: string) {
  if (dirty.value) {
    await saveCurrentFile();
  }
  const response = await api.file(path);
  selectedPath.value = response.path;
  content.value = response.content;
  savedContent.value = response.content;
  currentEditable.value = response.editable;
  editor?.setValue(response.content);
  editor?.updateOptions({ readOnly: !response.editable });
  editor?.focus();
}

async function saveCurrentFile() {
  if (!selectedPath.value || !dirty.value || !currentEditable.value) {
    return;
  }
  await api.saveFile(selectedPath.value, content.value);
  savedContent.value = content.value;
  status.value = "Vulnerable";
}

async function runAction(action: "tests" | "reset" | "check") {
  if (busy.value) {
    return;
  }
  busy.value = true;
  try {
    if (action !== "reset") {
      await saveCurrentFile();
      status.value = "Tests Running";
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
      consoleOutput.value = "Workspace reset to the vulnerable baseline.";
      selectedPath.value = "";
      content.value = "";
      savedContent.value = "";
      currentEditable.value = true;
      await loadFiles();
    }
  } catch (error) {
    status.value = "Tests Failed";
    consoleOutput.value = error instanceof Error ? error.message : String(error);
  } finally {
    busy.value = false;
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
    content.value = editor?.getValue() ?? "";
  });
  await nextTick();
  await loadStatus();
  await loadFiles();
});

onBeforeUnmount(() => {
  editor?.dispose();
});

watch(
  () => selectedPath.value,
  () => {
    if (editor && editor.getValue() !== content.value) {
      editor.setValue(content.value);
    }
  },
);
</script>

<template>
  <main class="lab-shell">
    <aside class="brief-panel">
      <div class="brand-block">
        <span class="eyebrow">Security Coding Lab</span>
        <h1>OpenClaw: Ownerless Gateway</h1>
        <p>Broken Access Control / Security Coding</p>
      </div>

      <section class="brief-section">
        <h2>Scenario</h2>
        <p>
          OpenClaw Gateway distinguishes command authorization from ownership. Authorized
          operators may use normal commands, but /config and /debug must remain owner-only. Fix
          the access-control regression without breaking allowed owner behavior or the internal
          read-only config flow.
        </p>
      </section>

      <section class="brief-section">
        <h2>Objectives</h2>
        <ul>
          <li>Block authorized non-owner access to <code>/config show</code>.</li>
          <li>Block authorized non-owner access to <code>/debug show</code>.</li>
          <li>Keep owners able to use <code>/config</code> and <code>/debug</code>.</li>
          <li>Keep internal read-only config access working.</li>
        </ul>
      </section>

      <section class="progress-panel">
        <div class="status-pill" :class="statusClass">{{ status }}</div>
        <div class="progress-row">
          <span>Visible tests</span>
          <strong>{{ lastTest ? (lastTest.ok ? "passing" : "failing") : "not run" }}</strong>
        </div>
        <div class="progress-row">
          <span>Editable files</span>
          <strong>{{ editableFileCount }}</strong>
        </div>
      </section>
    </aside>

    <section class="workbench">
      <header class="toolbar">
        <div>
          <span class="workspace-label">Workspace</span>
          <strong>{{ selectedFileName }}</strong>
          <span v-if="dirty" class="dirty-dot">Unsaved</span>
          <span v-if="!currentEditable" class="readonly-dot">Read-only</span>
        </div>
        <div class="actions">
          <button :disabled="busy" @click="runAction('tests')">Run Tests</button>
          <button :disabled="busy" @click="runAction('reset')">Reset Workspace</button>
          <button class="primary" :disabled="busy" @click="runAction('check')">
            Check Solution
          </button>
        </div>
      </header>

      <div class="editor-grid">
        <nav class="file-tree" aria-label="Lab files">
          <div class="tree-title">Lab files</div>
          <button
            v-for="file in files"
            :key="file.path"
            :class="{ selected: file.path === selectedPath, readonly: !file.editable }"
            @click="openFile(file.path)"
          >
            <span class="file-icon">TS</span>
            <span>{{ file.path }}</span>
          </button>
        </nav>

        <div class="editor-pane">
          <div ref="editorEl" class="editor-host" />
        </div>
      </div>

      <section class="console-pane" aria-label="Tests output">
        <div class="console-header">
          <strong>Tests / Console</strong>
          <span>No shell access. Backend runs the fixed vitest target only.</span>
        </div>
        <pre>{{ consoleOutput }}</pre>
      </section>
    </section>
  </main>
</template>
