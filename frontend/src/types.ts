export type LabStatus = "Vulnerable" | "Tests Running" | "Tests Failed" | "Lab Solved";
export type GatewayRole = "owner" | "operator";
export type GatewayCommand = "config_show" | "debug_show";
export type GatewayOutcome = "allowed" | "blocked" | "error";

export type TestRunSummary = {
  ok: boolean;
  exit_code: number;
  command: string;
  output: string;
  duration_ms: number;
};

export type LabStatusResponse = {
  name: string;
  category: string;
  status: LabStatus;
  workspace: string;
  allowed_files: string[];
  editable_files: string[];
  readable_files: string[];
  last_test: TestRunSummary | null;
  solved: boolean;
};

export type FileEntry = {
  path: string;
  name: string;
  language: string;
  editable: boolean;
};

export type TreeEntry = {
  path: string;
  name: string;
  type: "file" | "directory";
  language: string | null;
  editable: boolean;
  read_only: boolean;
  pinned: boolean;
  expandable: boolean;
};

export type TreeRow = TreeEntry & {
  depth: number;
};

export type FileListResponse = {
  files: FileEntry[];
};

export type TreeResponse = {
  path: string;
  entries: TreeEntry[];
  roots: string[];
  pinned_paths: string[];
  max_entries: number;
};

export type FileContentResponse = {
  path: string;
  content: string;
  editable: boolean;
};

export type TestRunResponse = {
  ok: boolean;
  status: LabStatus;
  result: TestRunSummary;
};

export type ResetResponse = {
  status: LabStatus;
  workspace: string;
};

export type CheckSolutionResponse = {
  ok: boolean;
  status: LabStatus;
  visible_tests: TestRunSummary;
  hidden_validation_passed: boolean;
  hidden_validation: string;
};

export type GatewaySimulationRequest = {
  role: GatewayRole;
  command: GatewayCommand;
};

export type GatewaySimulationResponse = GatewaySimulationRequest & {
  ok: boolean;
  display_command: string;
  outcome: GatewayOutcome;
  summary: string;
  safe_output: string;
  duration_ms: number;
};
