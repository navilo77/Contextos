"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ContextOsApiError,
  acceptDecision,
  createProjectExport,
  generateProject,
  getProjectDocument,
  getProjectWorkflow,
  listDecisions,
  projectExportUrl,
  rejectDecision,
  requestClarifications,
  saveClarificationAnswers,
  validateProjectDocuments,
  type ClarificationAnswerInput,
  type ClarificationQuestion,
  type Decision,
  type ProjectDocument,
  type ProjectExportResponse,
  type ProjectSummary,
  type ProjectWorkflowSnapshot,
} from "@/lib/context-os-api";

type Language = "bn" | "en";
type AnswerState = "answered" | "unknown" | "deferred";

const copy = {
  bn: {
    back: "Project তালিকায় ফিরুন",
    loading: "Workflow লোড হচ্ছে…",
    clarificationTitle: "প্রয়োজনীয় প্রশ্ন",
    clarificationIntro:
      "AI-তে project তথ্য পাঠানোর আগে আপনার স্পষ্ট সম্মতি প্রয়োজন। সম্মতি না দিলে কিছু পাঠানো হবে না।",
    consent: "প্রশ্ন তৈরির জন্য project তথ্য Google Gemini-তে পাঠাতে সম্মতি দিচ্ছি।",
    ask: "AI-কে প্রশ্ন তৈরি করতে বলুন",
    questionsEmpty: "কোনো clarification প্রশ্ন নেই।",
    answer: "আপনার উত্তর",
    answered: "উত্তর দেব",
    unknown: "এখনো জানি না",
    deferred: "পরে সিদ্ধান্ত নেব",
    saveAnswers: "উত্তর সংরক্ষণ করুন",
    generationTitle: "Documentation তৈরি",
    generationConsent: "Documentation তৈরির জন্য project ও উত্তর Google Gemini-তে পাঠাতে সম্মতি দিচ্ছি।",
    generate: "Documentation তৈরি করুন",
    documentsTitle: "Generated documents",
    openDocument: "সম্পূর্ণ document পড়ুন",
    loadingDocument: "Document লোড হচ্ছে…",
    reviewed: "আমি সম্পূর্ণ documentটি পড়েছি",
    validate: "Reviewed documents validate করুন",
    validationPassed: "সব document validation-এ উত্তীর্ণ হয়েছে।",
    validationFailed: "Validation ব্যর্থ হয়েছে। Export তৈরি করা যাবে না।",
    findingCount: "Finding",
    exportTitle: "Validated ZIP",
    createExport: "ZIP তৈরি করুন",
    download: "ZIP download করুন",
    busy: "কাজ চলছে…",
    apiFailure: "Workflow সম্পন্ন করা যায়নি। আবার চেষ্টা করুন।",
    answerRequired: "প্রতিটি প্রশ্নের উত্তর, unknown, অথবা deferred নির্বাচন করুন।",
    documentRequired: "Validation-এর আগে প্রতিটি document খুলে পড়ে নিশ্চিত করুন।",
  },
  en: {
    back: "Back to projects",
    loading: "Loading workflow…",
    clarificationTitle: "Clarifying questions",
    clarificationIntro:
      "Explicit consent is required before project information is sent to AI. Nothing is sent without it.",
    consent: "I consent to sending project information to Google Gemini to create questions.",
    ask: "Ask AI to create questions",
    questionsEmpty: "There are no clarification questions.",
    answer: "Your answer",
    answered: "I can answer",
    unknown: "I don't know yet",
    deferred: "I'll decide later",
    saveAnswers: "Save answers",
    generationTitle: "Generate documentation",
    generationConsent:
      "I consent to sending this project and its answers to Google Gemini to generate documentation.",
    generate: "Generate documentation",
    documentsTitle: "Generated documents",
    openDocument: "Read the full document",
    loadingDocument: "Loading document…",
    reviewed: "I have read this entire document",
    validate: "Validate reviewed documents",
    validationPassed: "All documents passed validation.",
    validationFailed: "Validation failed. An export cannot be created.",
    findingCount: "Findings",
    exportTitle: "Validated ZIP",
    createExport: "Create ZIP",
    download: "Download ZIP",
    busy: "Working…",
    apiFailure: "The workflow could not be completed. Please try again.",
    answerRequired: "Choose an answer, unknown, or deferred for every question.",
    documentRequired: "Open and review every document before validation.",
  },
} as const;

type AnswerDraft = {
  state: AnswerState | "";
  answer: string;
};

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ContextOsApiError ? error.message : fallback;
}

function initialAnswers(questions: ClarificationQuestion[]): Record<string, AnswerDraft> {
  return Object.fromEntries(
    questions.map((question) => [
      question.id,
      {
        state: question.answer_state ?? "",
        answer: question.answer ?? "",
      },
    ]),
  );
}

export function ProjectWorkflow({
  project,
  language,
  onBack,
}: {
  project: ProjectSummary;
  language: Language;
  onBack: () => void;
}) {
  const text = copy[language];
  const [snapshot, setSnapshot] = useState<ProjectWorkflowSnapshot | null>(null);
  const [documents, setDocuments] = useState<Record<string, ProjectDocument>>({});
  const [answers, setAnswers] = useState<Record<string, AnswerDraft>>({});
  const [answersDirty, setAnswersDirty] = useState(false);
  const [reviewedIds, setReviewedIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [clarificationConsent, setClarificationConsent] = useState(false);
  const [generationConsent, setGenerationConsent] = useState(false);
  const [validationId, setValidationId] = useState<string | null>(null);
  const [exportResource, setExportResource] = useState<ProjectExportResponse | null>(null);
  const generationKey = useRef<string | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [decisionsLoading, setDecisionsLoading] = useState(false);
  const [decisionBusyId, setDecisionBusyId] = useState<string | null>(null);

  const loadDecisions = useCallback(async () => {
    setDecisionsLoading(true);
    try {
      const res = await listDecisions(project.id);
      setDecisions(res.decisions);
    } catch (e) {
      // Don't fail workflow if decisions fail to load
      console.error(e);
    } finally {
      setDecisionsLoading(false);
    }
  }, [project.id]);

  useEffect(() => {
    void loadDecisions();
  }, [loadDecisions]);

  async function handleAcceptDecision(decisionId: string) {
    setDecisionBusyId(decisionId);
    setError(null);
    try {
      const updated = await acceptDecision(project.id, decisionId);
      setDecisions((cur) => cur.map((d) => (d.id === decisionId ? updated : d)));
    } catch (actionError) {
      setError(getErrorMessage(actionError, text.apiFailure));
    } finally {
      setDecisionBusyId(null);
    }
  }

  async function handleRejectDecision(decisionId: string) {
    setDecisionBusyId(decisionId);
    setError(null);
    try {
      const updated = await rejectDecision(project.id, decisionId);
      setDecisions((cur) => cur.map((d) => (d.id === decisionId ? updated : d)));
    } finally {
      setDecisionBusyId(null);
    }
  }

  const refresh = useCallback(async () => {
    const result = await getProjectWorkflow(project.id);
    setSnapshot(result);
    setAnswers(initialAnswers(result.clarification.questions));
    setAnswersDirty(false);
    setReviewedIds([]);
    setValidationId(result.validation?.id ?? null);
    setExportResource(result.exports.find((item) => item.status === "ready") ?? null);
  }, [project.id]);

  useEffect(() => {
    void refresh()
      .catch((loadError: unknown) => setError(getErrorMessage(loadError, text.apiFailure)))
      .finally(() => setLoading(false));
  }, [refresh, text.apiFailure]);

  async function runWorkflow(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (actionError) {
      setError(getErrorMessage(actionError, text.apiFailure));
    } finally {
      setBusy(false);
    }
  }

  async function loadDocument(documentId: string) {
    if (documents[documentId]) {
      return;
    }
    await runWorkflow(async () => {
      const document = await getProjectDocument(project.id, documentId);
      setDocuments((current) => ({ ...current, [documentId]: document }));
    });
  }

  function updateAnswerState(questionId: string, value: string) {
    if (value !== "" && value !== "answered" && value !== "unknown" && value !== "deferred") {
      return;
    }
    setAnswers((current) => ({
      ...current,
      [questionId]: {
        state: value,
        answer: current[questionId]?.answer ?? "",
      },
    }));
    setAnswersDirty(true);
  }

  function updateAnswerText(questionId: string, answer: string) {
    setAnswers((current) => ({
      ...current,
      [questionId]: {
        state: current[questionId]?.state ?? "",
        answer,
      },
    }));
    setAnswersDirty(true);
  }

  async function handleSaveAnswers() {
    const questions = snapshot?.clarification.questions ?? [];
    const payload: ClarificationAnswerInput[] = [];
    for (const question of questions) {
      const draft = answers[question.id];
      if (!draft?.state || (draft.state === "answered" && !draft.answer.trim())) {
        setError(text.answerRequired);
        return;
      }
      payload.push({
        question_id: question.id,
        answer_state: draft.state,
        ...(draft.state === "answered" ? { answer: draft.answer.trim() } : {}),
      });
    }
    await runWorkflow(async () => {
      const saved = await saveClarificationAnswers(project.id, payload);
      setSnapshot((current) => (current ? { ...current, clarification: saved } : current));
      setAnswers(initialAnswers(saved.questions));
      setAnswersDirty(false);
      await refresh();
    });
  }

  async function handleGenerate() {
    await runWorkflow(async () => {
      generationKey.current ??= crypto.randomUUID();
      await generateProject(project.id, generationKey.current);
      await refresh();
      generationKey.current = null;
      setGenerationConsent(false);
    });
  }

  async function handleValidation() {
    const documentIds = snapshot?.documents.map((document) => document.id) ?? [];
    if (
      !documentIds.length ||
      documentIds.some((documentId) => !documents[documentId] || !reviewedIds.includes(documentId))
    ) {
      setError(text.documentRequired);
      return;
    }
    await runWorkflow(async () => {
      const result = await validateProjectDocuments(project.id, documentIds);
      setValidationId(result.id);
      setSnapshot((current) => (current ? { ...current, validation: result } : current));
      await refresh();
    });
  }

  async function handleExport() {
    if (!validationId) {
      return;
    }
    await runWorkflow(async () => {
      const result = await createProjectExport(project.id, validationId);
      setExportResource(result);
      await refresh();
    });
  }

  const questions = snapshot?.clarification.questions ?? [];
  const allAnswersSaved =
    !answersDirty &&
    (questions.length === 0 || questions.every((question) => question.answer_state !== null));
  const readyExport = exportResource?.status === "ready" ? exportResource : null;

  return (
    <section className="project-workflow" aria-labelledby="workflow-title">
      <button className="button button-secondary" onClick={onBack} type="button">
        {text.back}
      </button>
      <div className="workflow-heading">
        <p className="section-label">{project.name}</p>
        <h2 id="workflow-title">{project.name}</h2>
        <p>Revision {project.current_revision}</p>
      </div>
      {loading && <p role="status">{text.loading}</p>}
      {error && (
        <p className="workbench-message workbench-error" role="alert">
          {error}
        </p>
      )}
      {!loading && snapshot && (
        <>
          <section className="workflow-card" aria-labelledby="clarification-title">
            <h3 id="clarification-title">{text.clarificationTitle}</h3>
            <p>{text.clarificationIntro}</p>
            {questions.length === 0 && !snapshot.clarification.consent_id && (
              <>
                <label className="workflow-consent">
                  <input
                    checked={clarificationConsent}
                    onChange={(event) => setClarificationConsent(event.target.checked)}
                    type="checkbox"
                  />
                  {text.consent}
                </label>
                <button
                  className="button button-primary"
                  disabled={!clarificationConsent || busy}
                  onClick={() =>
                    void runWorkflow(async () => {
                      const clarification = await requestClarifications(project.id);
                      setSnapshot((current) => (current ? { ...current, clarification } : current));
                      setAnswers(initialAnswers(clarification.questions));
                      setClarificationConsent(false);
                      await refresh();
                    })
                  }
                  type="button"
                >
                  {busy ? text.busy : text.ask}
                </button>
              </>
            )}
            {questions.length === 0 && snapshot.clarification.consent_id && (
              <p>{text.questionsEmpty}</p>
            )}
            {questions.length > 0 && (
              <div className="workflow-questions">
                {questions.map((question) => {
                  const draft = answers[question.id] ?? { state: "", answer: "" };
                  return (
                    <fieldset className="workflow-question" key={question.id}>
                      <legend>{question.question}</legend>
                      <p>{question.impact}</p>
                      <label>
                        {text.answer}
                        <select
                          onChange={(event) => updateAnswerState(question.id, event.target.value)}
                          value={draft.state}
                        >
                          <option value="">—</option>
                          <option value="answered">{text.answered}</option>
                          <option value="unknown">{text.unknown}</option>
                          <option value="deferred">{text.deferred}</option>
                        </select>
                      </label>
                      {draft.state === "answered" && (
                        <textarea
                          maxLength={2_000}
                          onChange={(event) => updateAnswerText(question.id, event.target.value)}
                          rows={3}
                          value={draft.answer}
                        />
                      )}
                    </fieldset>
                  );
                })}
                <button
                  className="button button-primary"
                  disabled={busy}
                  onClick={() => void handleSaveAnswers()}
                  type="button"
                >
                  {busy ? text.busy : text.saveAnswers}
                </button>
              </div>
            )}
          </section>

          <section className="workflow-card" aria-labelledby="generation-title">
            <h3 id="generation-title">{text.generationTitle}</h3>
            {snapshot.documents.length === 0 && (
              <>
                <label className="workflow-consent">
                  <input
                    checked={generationConsent}
                    onChange={(event) => setGenerationConsent(event.target.checked)}
                    type="checkbox"
                  />
                  {text.generationConsent}
                </label>
                <button
                  className="button button-primary"
                  disabled={!generationConsent || !allAnswersSaved || busy}
                  onClick={() => void handleGenerate()}
                  type="button"
                >
                  {busy ? text.busy : text.generate}
                </button>
              </>
            )}
            {snapshot.documents.length > 0 && (
              <>
                <h4>{text.documentsTitle}</h4>
                <div className="workflow-documents">
                  {snapshot.documents.map((document) => {
                    const content = documents[document.id];
                    return (
                      <article className="workflow-document" key={document.id}>
                        <h5>{document.path}</h5>
                        {!content ? (
                          <button
                            className="button button-secondary"
                            disabled={busy}
                            onClick={() => void loadDocument(document.id)}
                            type="button"
                          >
                            {busy ? text.loadingDocument : text.openDocument}
                          </button>
                        ) : (
                          <>
                            <pre>{content.content}</pre>
                            <label className="workflow-consent">
                              <input
                                checked={reviewedIds.includes(document.id)}
                                onChange={(event) =>
                                  setReviewedIds((current) =>
                                    event.target.checked
                                      ? [...current, document.id]
                                      : current.filter((id) => id !== document.id),
                                  )
                                }
                                type="checkbox"
                              />
                              {text.reviewed}
                            </label>
                          </>
                        )}
                      </article>
                    );
                  })}
                </div>
                {snapshot.validation?.status === "passed" ? (
                  <p className="workbench-message workbench-success" role="status">
                    {text.validationPassed}
                  </p>
                ) : snapshot.validation?.status === "failed" ? (
                  <p className="workbench-message workbench-error" role="alert">
                    {text.validationFailed} ({text.findingCount}:{" "}
                    {snapshot.validation.finding_count})
                  </p>
                ) : (
                  <button
                    className="button button-primary"
                    disabled={busy}
                    onClick={() => void handleValidation()}
                    type="button"
                  >
                    {busy ? text.busy : text.validate}
                  </button>
                )}
              </>
            )}
          </section>

        </>
      )}
    </section>
  );
}
