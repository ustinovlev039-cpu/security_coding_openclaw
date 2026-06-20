import type {
  CheckSolutionResponse,
  FileContentResponse,
  FileListResponse,
  LabStatusResponse,
  ResetResponse,
  TestRunResponse,
} from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => request<LabStatusResponse>("/api/lab/status"),
  files: () => request<FileListResponse>("/api/lab/files"),
  file: (path: string) => request<FileContentResponse>(`/api/lab/files/${path}`),
  saveFile: (path: string, content: string) =>
    request<{ path: string; saved: boolean; status: string }>(`/api/lab/files/${path}`, {
      method: "PUT",
      headers: jsonHeaders,
      body: JSON.stringify({ content }),
    }),
  runTests: () => request<TestRunResponse>("/api/lab/run-tests", { method: "POST" }),
  reset: () => request<ResetResponse>("/api/lab/reset", { method: "POST" }),
  checkSolution: () =>
    request<CheckSolutionResponse>("/api/lab/check-solution", { method: "POST" }),
};

