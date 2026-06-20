export type LabStatus = "Vulnerable" | "Tests Running" | "Tests Failed" | "Lab Solved";

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

export type FileListResponse = {
  files: FileEntry[];
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
