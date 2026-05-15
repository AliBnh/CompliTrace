import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAppState } from "../../app/state";
import { createAudit, getSections } from "../../lib/api";
import type { SectionOut } from "../../lib/types";
import { AlignLeft, BookOpenText, Hash, Sparkles } from "lucide-react";

export function SectionsPage() {
  const { documentId, setAuditId, selectedGroupId } = useAppState();
  const [sections, setSections] = useState<SectionOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [auditLoading, setAuditLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!documentId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    getSections(documentId)
      .then(setSections)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [documentId]);

  const extractionStats = useMemo(() => {
    const contentChars = sections.reduce(
      (sum, section) => sum + section.content.length,
      0,
    );
    return {
      sections: sections.length,
      avgLength: sections.length
        ? Math.round(contentChars / sections.length)
        : 0,
      withPageRef: sections.filter(
        (item) => item.page_start != null || item.page_end != null,
      ).length,
    };
  }, [sections]);

  async function startAudit() {
    if (!documentId) return;
    setAuditLoading(true);
    setError(null);
    try {
      const audit = await createAudit(documentId, selectedGroupId);
      setAuditId(audit.id);
      navigate("/findings");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start audit");
    } finally {
      setAuditLoading(false);
    }
  }

  if (!documentId)
    return (
      <EmptyState message="No document uploaded yet. Start on the Upload page." />
    );

  return (
    <section className="space-y-6">
      <header className="surface-card p-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="section-title">Sections review</h1>
            <p className="section-subtitle">
              Validate extracted policy structure before launching the GDPR
              audit.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={startAudit}
              disabled={auditLoading || loading || sections.length === 0}
              className="btn-primary"
            >
              {auditLoading ? "Audit in progress…" : "Start audit"}
            </button>
          </div>
        </div>

        {auditLoading && (
          <div className="mt-6 rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 to-blue-50/50 p-6 backdrop-blur-sm">
            <div className="flex items-start gap-4">
              <div className="relative flex h-8 w-8 items-center justify-center">
                <div className="absolute inset-0 animate-spin rounded-full border-2 border-transparent border-t-blue-500 border-r-blue-500"></div>
                <Sparkles className="h-4 w-4 text-blue-600" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-blue-900">
                  AI Agent analyzing your document
                </h3>
                <p className="mt-1 text-sm text-blue-700">
                  Our compliance engine is processing your policy against GDPR
                  requirements, identifying obligations, and classifying
                  compliance risks across all sections. This typically takes
                  60-90 seconds.
                </p>
                <div className="mt-3 text-xs text-blue-600 font-medium">
                  Performing deep compliance analysis…
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <MetricCard
            label="Sections"
            value={String(extractionStats.sections)}
            icon={<Hash className="h-5 w-5" />}
          />
          <MetricCard
            label="Avg chars / section"
            value={String(extractionStats.avgLength)}
            icon={<AlignLeft className="h-5 w-5" />}
          />
          <MetricCard
            label="With page reference"
            value={String(extractionStats.withPageRef)}
            icon={<BookOpenText className="h-5 w-5" />}
          />
        </div>
      </header>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="surface-card p-7 text-sm text-gray-500">
          Loading extracted sections…
        </div>
      ) : (
        <div className="space-y-3.5">
          {sections.map((section) => (
            <article
              key={section.id}
              className="animate-rise rounded-xl border border-slate-200 bg-white p-5 shadow-[0_2px_10px_rgba(15,23,42,0.04)]"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-sm font-semibold leading-6 text-slate-900">
                  {formatSectionHeading(section)}
                </h2>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-600">
                  {formatPageRange(section.page_start, section.page_end)}
                </span>
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-600">
                {section.content}
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function MetricCard({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: ReactNode;
}) {
  return (
    <article className="relative overflow-hidden rounded-lg border border-slate-200/70 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.06)]">
      <div className="pointer-events-none absolute -bottom-3 -right-3 text-slate-200/70">
        <div className="[&>svg]:h-12 [&>svg]:w-12">{icon}</div>
      </div>
      <p className="text-xs font-medium uppercase tracking-widest text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-3xl font-bold tracking-tight text-slate-900">
        {value}
      </p>
    </article>
  );
}

function formatPageRange(start: number | null, end: number | null) {
  if (start == null && end == null) return "Page n/a";
  if (start != null && end != null && start !== end)
    return `Pages ${start}-${end}`;
  return `Page ${start ?? end}`;
}

function formatSectionHeading(section: SectionOut): string {
  const title = (section.section_title ?? "").trim();
  if (title) return title;
  return `Section ${section.section_order}`;
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="surface-card flex flex-col items-center justify-center px-6 py-16 text-center">
      <svg
        className="mb-3 h-10 w-10 text-gray-300"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
        />
      </svg>
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );
}
