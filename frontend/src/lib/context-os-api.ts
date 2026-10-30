export type ProjectSummary = {
  id: string;
  name: string;
  slug: string;
  status: string;
  current_revision: number;
};

export type ProjectListResponse = {
  items: ProjectSummary[];
  limit: number;
  offset: number;
  next_cursor: string | null;
};

export type ProjectCreatedResponse = {
  project: ProjectSummary;
  revision_id: string;
};

export type ClarificationQuestion = {
  id: string;
  question: string;
  impact: string;
  blocking: boolean;
  status: string;
  answer_state: "answered" | "unknown" | "deferred" | null;
  answer: string | null;
};

export type ClarificationResponse = {
  project_id: string;
  revision_id: string;
  consent_id: string | null;
  questions: ClarificationQuestion[];
};

export type ClarificationAnswerInput = {
  question_id: string;
  answer_state: "answered" | "unknown" | "deferred";
  answer?: string;
};

export type ProjectDocumentSummary = {
  id: string;
  path: string;
  document_kind: string;
  sha256: string;
};

export type ProjectDocument = ProjectDocumentSummary & {
  content_format: string;
  content: string;
};

export type ValidationResponse = {
  id: string;
  status: string;
  checked_document_count: number;
  finding_count: number;
};

export type ProjectExportResponse = {
  id: string;
  status: string;
  zip_sha256: string;
  download_path: string;
};

export type Decision = {
  id: string;
  statement: string;
  rationale: string | null;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
};

export type DecisionListResponse = {
  decisions: Decision[];
};

export type CreateProjectInput = {
  name: string;
  idea: string;
  audience: string;
  platform: string;
  constraints: string;
  technology: string;
  language: string;
  profile: "compact" | "detailed";
};

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_CONTEXT_OS_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export class ContextOsApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
    this.name = "ContextOsApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isProjectSummary(value: unknown): value is ProjectSummary {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    typeof value.slug === "string" &&
    typeof value.status === "string" &&
    typeof value.current_revision === "number"
  );
}

function parseProjectList(payload: unknown): ProjectListResponse {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.items) ||
    !payload.items.every(isProjectSummary) ||
    typeof payload.limit !== "number" ||
    typeof payload.offset !== "number" ||
    (payload.next_cursor !== null && typeof payload.next_cursor !== "string")
  ) {
    throw new ContextOsApiError(
      "The local API returned an invalid project list.",
      200,
      "invalid_api_response",
    );
  }
  return {
    items: payload.items,
    limit: payload.limit,
    offset: payload.offset,
    next_cursor: payload.next_cursor,
  };
}

function parseProjectCreated(payload: unknown): ProjectCreatedResponse {
  if (
    !isRecord(payload) ||
    !isRecord(payload.project) ||
    !isProjectSummary(payload.project) ||
    typeof payload.revision_id !== "string"
  ) {
    throw new ContextOsApiError(
      "The local API returned an invalid project resource.",
      200,
      "invalid_api_response",
    );
  }
  return {
    project: payload.project,
    revision_id: payload.revision_id,
  };
}

function isClarificationQuestion(value: unknown): value is ClarificationQuestion {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.question === "string" &&
    typeof value.impact === "string" &&
    typeof value.blocking === "boolean" &&
    typeof value.status === "string" &&
    (value.answer_state === null ||
      value.answer_state === "answered" ||
      value.answer_state === "unknown" ||
      value.answer_state === "deferred") &&
    (value.answer === null || typeof value.answer === "string")
  );
}

function parseClarification(payload: unknown): ClarificationResponse {
  if (
    !isRecord(payload) ||
    typeof payload.project_id !== "string" ||
    typeof payload.revision_id !== "string" ||
    (payload.consent_id !== null && typeof payload.consent_id !== "string") ||
    !Array.isArray(payload.questions) ||
    !payload.questions.every(isClarificationQuestion)
  ) {
    throw new ContextOsApiError(
      "The local API returned invalid clarification data.",
      200,
      "invalid_api_response",
    );
  }
  return {
    project_id: payload.project_id,
    revision_id: payload.revision_id,
    consent_id: payload.consent_id,
    questions: payload.questions,
  };
}

function isProjectDocumentSummary(value: unknown): value is ProjectDocumentSummary {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.path === "string" &&
    typeof value.document_kind === "string" &&
    typeof value.sha256 === "string"
  );
}

function parseProjectDocuments(payload: unknown): ProjectDocumentSummary[] {
  if (!Array.isArray(payload) || !payload.every(isProjectDocumentSummary)) {
    throw new ContextOsApiError(
      "The local API returned invalid document data.",
      200,
      "invalid_api_response",
    );
  }
  return payload;
}

function isProjectDocument(value: unknown): value is ProjectDocument {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.path !== "string" ||
    typeof value.document_kind !== "string" ||
    typeof value.sha256 !== "string" ||
    typeof value.content_format !== "string" ||
    typeof value.content !== "string"
  ) {
    return false;
  }
  return true;
}

function parseProjectDocument(payload: unknown): ProjectDocument {
  if (!isProjectDocument(payload)) {
    throw new ContextOsApiError(
      "The local API returned an invalid document.",
      200,
      "invalid_api_response",
    );
  }
  return payload;
}

function parseValidation(payload: unknown): ValidationResponse {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    typeof payload.status !== "string" ||
    typeof payload.checked_document_count !== "number" ||
    typeof payload.finding_count !== "number"
  ) {
    throw new ContextOsApiError(
      "The local API returned an invalid validation report.",
      200,
      "invalid_api_response",
    );
  }
  return {
    id: payload.id,
    status: payload.status,
    checked_document_count: payload.checked_document_count,
    finding_count: payload.finding_count,
  };
}

function parseProjectExport(payload: unknown): ProjectExportResponse {
  if (
    !isRecord(payload) ||
    typeof payload.id !== "string" ||
    typeof payload.status !== "string" ||
    typeof payload.zip_sha256 !== "string" ||
    typeof payload.download_path !== "string" ||
    !payload.download_path.startsWith("/api/v1/projects/")
  ) {
    throw new ContextOsApiError(
      "The local API returned an invalid export resource.",
      200,
      "invalid_api_response",
    );
  }
  return {
    id: payload.id,
    status: payload.status,
    zip_sha256: payload.zip_sha256,
    download_path: payload.download_path,
  };
}

function parseProjectWorkflowSnapshot(payload: unknown): ProjectWorkflowSnapshot {
  if (
    !isRecord(payload) ||
    typeof payload.project_id !== "string" ||
    typeof payload.revision_id !== "string" ||
    !isRecord(payload.clarification) ||
    !Array.isArray(payload.documents) ||
    !payload.documents.every(isProjectDocumentSummary) ||
    !Array.isArray(payload.exports)
  ) {
    throw new ContextOsApiError(
      "The local API returned an invalid project workflow.",
      200,
      "invalid_api_response",
    );
  }
  const clarification = parseClarification(payload.clarification);
  const validation = payload.validation === null ? null : parseValidation(payload.validation);
  const exports = payload.exports.map(parseProjectExport);
  if (
    clarification.project_id !== payload.project_id ||
    clarification.revision_id !== payload.revision_id
  ) {
    throw new ContextOsApiError(
      "The local API returned mismatched project workflow data.",
      200,
      "invalid_api_response",
    );
  }
  return {
    project_id: payload.project_id,
    revision_id: payload.revision_id,
    clarification,
    documents: payload.documents,
    validation,
    exports,
  };
}

function isDecision(value: unknown): value is Decision {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.statement === "string" &&
    (value.rationale === null || typeof value.rationale === "string") &&
    typeof value.status === "string" &&
    (value.decided_by === null || typeof value.decided_by === "string") &&
    (value.decided_at === null || typeof value.decided_at === "string")
  );
}

function parseDecisions(payload: unknown): DecisionListResponse {
  if (!isRecord(payload) || !Array.isArray(payload.decisions) || !payload.decisions.every(isDecision)) {
    throw new ContextOsApiError("The local API returned invalid decision data.", 200, "invalid_api_response");
  }
  return { decisions: payload.decisions };
}

function parseDecision(payload: unknown): Decision {
  if (!isDecision(payload)) {
    throw new ContextOsApiError("The local API returned invalid decision data.", 200, "invalid_api_response");
  }
  return payload;
}
  const detail = isRecord(payload) ? payload.detail : undefined;
  const nestedMessage =
    isRecord(detail) && typeof detail.message === "string" ? detail.message : undefined;
  const message =
    (isRecord(payload) && typeof payload.message === "string" && payload.message) ||
    (typeof detail === "string" && detail) ||
    nestedMessage ||
    `The local API returned HTTP ${status}.`;
  const code =
    (isRecord(payload) && typeof payload.code === "string" && payload.code) ||
    (isRecord(detail) && typeof detail.code === "string" && detail.code) ||
    "api_request_failed";
  return new ContextOsApiError(message, status, code);
}

async function requestJson<T>(
  path: string,
  parse: (payload: unknown) => T,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1${path}`, {
      ...init,
      cache: "no-store",
      headers,
    });
  } catch (error) {
    if (!(error instanceof TypeError)) {
      throw error;
    }
    throw new ContextOsApiError(
      "The local Context OS API could not be reached.",
      0,
      "api_unavailable",
    );
  }

  const payload: unknown = await response.json().catch((error: unknown) => {
    if (!(error instanceof SyntaxError)) {
      throw error;
    }
    return null;
  });
  if (!response.ok) {
    throw errorFromResponse(payload, response.status);
  }
  return parse(payload);
}

export function listProjects(cursor?: string): Promise<ProjectListResponse> {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) {
    query.set("cursor", cursor);
  }
  return requestJson(`/projects?${query.toString()}`, parseProjectList);
}

export function createProject(input: CreateProjectInput): Promise<ProjectCreatedResponse> {
  return requestJson("/projects", parseProjectCreated, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getClarifications(projectId: string): Promise<ClarificationResponse> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/clarifications`,
    parseClarification,
  );
}

export function requestClarifications(projectId: string): Promise<ClarificationResponse> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/clarifications`,
    parseClarification,
    {
      method: "POST",
      body: JSON.stringify({ consent: true }),
    },
  );
}

export function saveClarificationAnswers(
  projectId: string,
  answers: ClarificationAnswerInput[],
): Promise<ClarificationResponse> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/clarifications/answers`,
    parseClarification,
    {
      method: "PUT",
      body: JSON.stringify({ answers }),
    },
  );
}

export function generateProject(
  projectId: string,
  idempotencyKey: string,
): Promise<{ documents: ProjectDocumentSummary[]; status: string }> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/generate`,
    (payload) => {
      if (
        !isRecord(payload) ||
        typeof payload.status !== "string" ||
        !Array.isArray(payload.documents) ||
        !payload.documents.every(isProjectDocumentSummary)
      ) {
        throw new ContextOsApiError(
          "The local API returned invalid generation data.",
          200,
          "invalid_api_response",
        );
      }
      return { documents: payload.documents, status: payload.status };
    },
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ consent: true }),
    },
  );
}

export function listProjectDocuments(projectId: string): Promise<ProjectDocumentSummary[]> {
  return requestJson(`/projects/${encodeURIComponent(projectId)}/documents`, parseProjectDocuments);
}

export function getProjectWorkflow(projectId: string): Promise<ProjectWorkflowSnapshot> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/workflow`,
    parseProjectWorkflowSnapshot,
  );
}

export function getProjectDocument(
  projectId: string,
  documentId: string,
): Promise<ProjectDocument> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`,
    parseProjectDocument,
  );
}

export function validateProjectDocuments(
  projectId: string,
  documentIds: string[],
): Promise<ValidationResponse> {
  return requestJson(`/projects/${encodeURIComponent(projectId)}/validate`, parseValidation, {
    method: "POST",
    body: JSON.stringify({ approved: true, document_ids: documentIds }),
  });
}

export function createProjectExport(
  projectId: string,
  validationReportId: string,
): Promise<ProjectExportResponse> {
  return requestJson(`/projects/${encodeURIComponent(projectId)}/exports`, parseProjectExport, {
    method: "POST",
    body: JSON.stringify({ validation_report_id: validationReportId, confirm: true }),
  });
}

export function listDecisions(projectId: string): Promise<DecisionListResponse> {
  return requestJson(`/projects/${encodeURIComponent(projectId)}/decisions`, parseDecisions);
}

export function acceptDecision(projectId: string, decisionId: string, reason?: string): Promise<Decision> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/decisions/${encodeURIComponent(decisionId)}/accept`,
    parseDecision,
    {
      method: "POST",
      body: JSON.stringify({ approved: true, reason: reason || null }),
    },
  );
}

export function rejectDecision(projectId: string, decisionId: string, reason?: string): Promise<Decision> {
  return requestJson(
    `/projects/${encodeURIComponent(projectId)}/decisions/${encodeURIComponent(decisionId)}/reject`,
    parseDecision,
    {
      method: "POST",
      body: JSON.stringify({ approved: false, reason: reason || null }),
    },
  );
}

function errorFromResponse(payload: unknown, status: number): ContextOsApiError {
  if (!downloadPath.startsWith("/api/v1/projects/")) {
    throw new ContextOsApiError(
      "The local API returned an invalid export path.",
      200,
      "invalid_api_response",
    );
  }
  return `${API_BASE_URL}${downloadPath}`;
}
