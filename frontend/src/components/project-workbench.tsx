"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ContextOsApiError,
  createProject,
  listProjects,
  type CreateProjectInput,
  type ProjectSummary,
} from "@/lib/context-os-api";
import { ProjectWorkflow } from "@/components/project-workflow";

type Language = "bn" | "en";

type ProjectForm = CreateProjectInput;

function makeInitialForm(language: Language): ProjectForm {
  return {
    name: "",
    idea: "",
    audience: "",
    platform: "",
    constraints: "",
    technology: "",
    language: language === "bn" ? "বাংলা" : "English",
    profile: "compact",
  };
}

const copy = {
  bn: {
    label: "প্রজেক্ট ওয়ার্কস্পেস",
    title: "Context package তৈরি শুরু করুন",
    intro:
      "আপনার project-এর প্রাথমিক তথ্য লোকাল PostgreSQL-এ সংরক্ষিত হবে। AI-তে কিছু পাঠানোর আগে আলাদা সম্মতি চাওয়া হবে।",
    formTitle: "নতুন project",
    name: "Project-এর নাম",
    idea: "আপনার idea",
    audience: "কারা ব্যবহার করবেন (ঐচ্ছিক)",
    platform: "পছন্দের platform (ঐচ্ছিক)",
    constraints: "জানা সীমাবদ্ধতা (ঐচ্ছিক)",
    technology: "পছন্দের technology (ঐচ্ছিক)",
    language: "Documentation-এর ভাষা",
    profile: "Package-এর ধরন",
    compact: "Compact",
    detailed: "Detailed",
    submit: "Project সংরক্ষণ করুন",
    saving: "সংরক্ষণ হচ্ছে…",
    projectsTitle: "আপনার project",
    loading: "Project লোড হচ্ছে…",
    empty: "এখনো কোনো project নেই। প্রথম project তৈরি করুন।",
    revision: "Revision",
    loadMore: "আরও project দেখুন",
    created: "Project তৈরি হয়েছে।",
    retry: "আবার চেষ্টা করুন",
    required: "Project-এর নাম ও idea লিখুন।",
    apiFailure: "Project সংরক্ষণ করা যায়নি। API status ও database migration পরীক্ষা করুন।",
  },
  en: {
    label: "PROJECT WORKSPACE",
    title: "Start a context package",
    intro:
      "Your initial project details are stored in local PostgreSQL. Separate consent is required before anything is sent to AI.",
    formTitle: "New project",
    name: "Project name",
    idea: "Your idea",
    audience: "Intended users (optional)",
    platform: "Preferred platform (optional)",
    constraints: "Known constraints (optional)",
    technology: "Preferred technology (optional)",
    language: "Documentation language",
    profile: "Package profile",
    compact: "Compact",
    detailed: "Detailed",
    submit: "Save project",
    saving: "Saving…",
    projectsTitle: "Your projects",
    loading: "Loading projects…",
    empty: "No projects yet. Create your first project.",
    revision: "Revision",
    loadMore: "Load more projects",
    created: "Project created.",
    retry: "Try again",
    required: "Enter a project name and idea.",
    apiFailure: "Could not save the project. Check API status and database migrations.",
  },
} as const;

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ContextOsApiError ? error.message : fallback;
}

export function ProjectWorkbench({ language }: { language: Language }) {
  const text = copy[language];
  const [form, setForm] = useState<ProjectForm>(() => makeInitialForm(language));
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<ProjectSummary | null>(null);

  const loadProjects = useCallback(
    async (cursor?: string, append = false) => {
      setLoading(true);
      setError(null);
      try {
        const page = await listProjects(cursor);
        setProjects((current) => (append ? [...current, ...page.items] : page.items));
        setNextCursor(page.next_cursor);
      } catch (loadError) {
        setError(getErrorMessage(loadError, text.apiFailure));
      } finally {
        setLoading(false);
      }
    },
    [text.apiFailure],
  );

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  function updateField<K extends keyof ProjectForm>(field: K, value: ProjectForm[K]) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.name.trim() || !form.idea.trim()) {
      setError(text.required);
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createProject({
        ...form,
        name: form.name.trim(),
        idea: form.idea.trim(),
        audience: form.audience.trim(),
        platform: form.platform.trim(),
        constraints: form.constraints.trim(),
        technology: form.technology.trim(),
      });
      setForm(makeInitialForm(language));
      setSelectedProject(created.project);
      setNotice(text.created);
      await loadProjects();
    } catch (saveError) {
      setError(getErrorMessage(saveError, text.apiFailure));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="workbench section-wrap" id="projects" aria-labelledby="workbench-title">
      <div className="workbench-heading">
        <p className="section-label">{text.label}</p>
        <h2 id="workbench-title">{text.title}</h2>
        <p>{text.intro}</p>
      </div>
      {selectedProject ? (
        <ProjectWorkflow
          language={language}
          onBack={() => setSelectedProject(null)}
          project={selectedProject}
        />
      ) : (
        <div className="workbench-grid">
          <form className="project-form" onSubmit={handleSubmit}>
            <h3>{text.formTitle}</h3>
            <label>
              {text.name}
              <input
                autoComplete="off"
                maxLength={120}
                name="name"
                onChange={(event) => updateField("name", event.target.value)}
                required
                value={form.name}
              />
            </label>
            <label>
              {text.idea}
              <textarea
                maxLength={20_000}
                name="idea"
                onChange={(event) => updateField("idea", event.target.value)}
                required
                rows={5}
                value={form.idea}
              />
            </label>
            <label>
              {text.audience}
              <input
                maxLength={1_000}
                name="audience"
                onChange={(event) => updateField("audience", event.target.value)}
                value={form.audience}
              />
            </label>
            <label>
              {text.platform}
              <input
                maxLength={500}
                name="platform"
                onChange={(event) => updateField("platform", event.target.value)}
                value={form.platform}
              />
            </label>
            <label>
              {text.constraints}
              <textarea
                maxLength={2_000}
                name="constraints"
                onChange={(event) => updateField("constraints", event.target.value)}
                rows={3}
                value={form.constraints}
              />
            </label>
            <label>
              {text.technology}
              <input
                maxLength={500}
                name="technology"
                onChange={(event) => updateField("technology", event.target.value)}
                value={form.technology}
              />
            </label>
            <div className="project-form-options">
              <label>
                {text.language}
                <input
                  maxLength={32}
                  name="language"
                  onChange={(event) => updateField("language", event.target.value)}
                  required
                  value={form.language}
                />
              </label>
              <label>
                {text.profile}
                <select
                  name="profile"
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === "compact" || value === "detailed") {
                      updateField("profile", value);
                    }
                  }}
                  value={form.profile}
                >
                  <option value="compact">{text.compact}</option>
                  <option value="detailed">{text.detailed}</option>
                </select>
              </label>
            </div>
            {error && (
              <p className="workbench-message workbench-error" role="alert">
                {error}
              </p>
            )}
            {notice && (
              <p className="workbench-message workbench-success" role="status">
                {notice}
              </p>
            )}
            <button
              className="button button-primary project-submit"
              disabled={saving}
              type="submit"
            >
              {saving ? text.saving : text.submit}
            </button>
          </form>

          <section className="project-list" aria-labelledby="project-list-title">
            <h3 id="project-list-title">{text.projectsTitle}</h3>
            {loading && <p role="status">{text.loading}</p>}
            {!loading && projects.length === 0 && !error && <p>{text.empty}</p>}
            <ul>
              {projects.map((project) => (
                <li className="project-list-item" key={project.id}>
                  <button
                    className="project-list-item-button"
                    onClick={() => setSelectedProject(project)}
                    type="button"
                  >
                    <span className="project-list-mark" aria-hidden="true">
                      C
                    </span>
                    <span className="project-list-copy">
                      <strong>{project.name}</strong>
                      <span>
                        {text.revision} {project.current_revision}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
            {error && !projects.length && (
              <button
                className="button button-secondary"
                onClick={() => void loadProjects()}
                type="button"
              >
                {text.retry}
              </button>
            )}
            {nextCursor && (
              <button
                className="button button-secondary"
                disabled={loading}
                onClick={() => void loadProjects(nextCursor, true)}
                type="button"
              >
                {text.loadMore}
              </button>
            )}
          </section>
        </div>
      )}
    </section>
  );
}
