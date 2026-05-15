import { useEffect, useMemo, useState } from "react";

import { useAppState } from "../../app/state";
import {
  createReport,
  downloadReport,
  getAnalysis,
  getAudit,
  getDocument,
  getExportContract,
  getFindings,
  getReport,
  getReview,
  getSections,
} from "../../lib/api";
import {
  aggregateChecklistCounts,
  aggregateRawPublishedCounts,
  buildComplianceChecklist,
  buildFindingsPresentation,
  splitFindingsByScope,
} from "../../lib/presentation";
import type {
  AnalysisItemOut,
  AuditOut,
  DocumentOut,
  ExportContractOut,
  PublishedFindingOut,
  ReportOut,
  ReviewItemOut,
  SectionOut,
} from "../../lib/types";

export function ReportPage() {
  const { auditId, documentId } = useAppState();
  const [reviewRows, setReviewRows] = useState<ReviewItemOut[]>([]);
  const [analysisRows, setAnalysisRows] = useState<AnalysisItemOut[]>([]);
  const [publishedRows, setPublishedRows] = useState<PublishedFindingOut[]>([]);
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>(
    {},
  );
  const [report, setReport] = useState<ReportOut | null>(null);
  const [exportContract, setExportContract] =
    useState<ExportContractOut | null>(null);
  const [status, setStatus] = useState<"idle" | "generating" | "ready">("idle");
  const [complianceScore, setComplianceScore] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [audit, setAudit] = useState<AuditOut | null>(null);
  const [docMetadata, setDocMetadata] = useState<DocumentOut | null>(null);

  useEffect(() => {
    if (!documentId) return;
    getSections(documentId)
      .then((sections) =>
        setSectionsById(Object.fromEntries(sections.map((s) => [s.id, s]))),
      )
      .catch(() => setSectionsById({}));
  }, [documentId]);

  useEffect(() => {
    if (!auditId) return;
    Promise.allSettled([
      getReview(auditId),
      getFindings(auditId),
      getAnalysis(auditId),
    ]).then(([reviewResult, publishedResult, analysisResult]) => {
      if (reviewResult.status === "fulfilled")
        setReviewRows(reviewResult.value);
      else setError("Unable to load review findings");
      if (publishedResult.status === "fulfilled")
        setPublishedRows(publishedResult.value);
      else setPublishedRows([]);
      setAnalysisRows(
        analysisResult.status === "fulfilled" ? analysisResult.value : [],
      );
    });
    getExportContract(auditId)
      .then(setExportContract)
      .catch(() => setExportContract(null));
    getAudit(auditId)
      .then((a) => {
        setAudit(a);
        setComplianceScore(a.compliance_score ?? null);
      })
      .catch(() => {});
  }, [auditId]);

  useEffect(() => {
    if (!documentId) return;
    getDocument(documentId)
      .then(setDocMetadata)
      .catch(() => setDocMetadata(null));
  }, [documentId]);

  useEffect(() => {
    if (!auditId || status !== "generating") return;
    const timer = setInterval(async () => {
      try {
        const r = await getReport(auditId);
        setReport(r);
        if (r.status === "ready") setStatus("ready");
      } catch {
        // noop
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [auditId, status]);

  const presentation = useMemo(
    () =>
      buildFindingsPresentation({
        publishedRows,
        reviewRows,
        analysisRows,
        sectionsById,
        publishedBlocked: false,
      }),
    [publishedRows, reviewRows, analysisRows, sectionsById],
  );
  const exportRows = presentation.publishedVisibleFindings;
  const checklist = useMemo(
    () => buildComplianceChecklist(reviewRows),
    [reviewRows],
  );
  const checklistCounts = useMemo(
    () => aggregateChecklistCounts(checklist),
    [checklist],
  );
  const counts =
    exportContract?.dataset_used === "zero"
      ? {
          ...checklistCounts,
          non_compliant: 0,
          not_applicable:
            checklistCounts.not_applicable + checklistCounts.non_compliant,
        }
      : (exportContract?.counts_by_status ??
        aggregateRawPublishedCounts(publishedRows));
  const { documentFindings, sectionFindings } =
    splitFindingsByScope(exportRows);
  const exportReady = exportContract?.export_allowed !== false;

  async function generate() {
    if (!auditId) return;
    setError(null);
    setStatus("generating");
    if (!exportReady) {
      setStatus("idle");
      const reason = exportContract?.blocker_reasons?.[0]
        ? toUserBlocker(exportContract.blocker_reasons[0])
        : "Export is temporarily unavailable.";
      setError(`PDF export is unavailable: ${reason}`);
      return;
    }

    try {
      await createReport(auditId);
    } catch (e) {
      setStatus("idle");
      setError(e instanceof Error ? e.message : "Failed to generate report");
    }
  }

  async function handleDownload() {
    if (!auditId) return;
    setDownloading(true);
    setError(null);
    try {
      const blob = await downloadReport(auditId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;

      // Build filename: v{version} {document_title} audit {date}.pdf
      let filename = "audit";
      if (docMetadata?.title) {
        const version = audit?.version_number ?? 0;
        const title = docMetadata.title.replace(/\.pdf$/i, "");
        const date = report?.created_at
          ? new Date(report.created_at).toISOString().split("T")[0]
          : new Date().toISOString().split("T")[0];
        filename = `v${version} ${title} audit ${date}`;
      }

      link.download = `${filename}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to download report");
    } finally {
      setDownloading(false);
    }
  }

  if (!auditId)
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
        <p className="text-sm text-gray-500">Run an audit first.</p>
      </div>
    );

  return (
    <section className="space-y-6">
      <header className="surface-card p-7">
        <h1 className="section-title">Report center</h1>
        <p className="section-subtitle">
          Generate and download an executive PDF for this audit.
        </p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          {[
            ["Compliant", counts.compliant],
            ["Partially compliant", counts.partially_compliant],
            ["Non-compliant", counts.non_compliant],
            ["Not applicable", counts.not_applicable],
            ["Total", counts.total],
          ].map(([label, count]) => (
            <article
              key={String(label)}
              className={`metric-card ${metricTone(String(label))}`}
            >
              <div className="h-6 text-xs font-medium uppercase tracking-wide opacity-80 line-clamp-1 flex items-center">
                {label}
              </div>
              <div className="mt-1.5 text-2xl font-semibold">{count}</div>
            </article>
          ))}
          {complianceScore !== null && (
            <article
              className={`metric-card ${scoreMetricTone(complianceScore)}`}
            >
              <div className="h-6 text-xs font-medium uppercase tracking-wide opacity-80 line-clamp-1 flex items-center">
                Compliance Score
              </div>
              <div className="mt-1.5 text-2xl font-semibold">
                {complianceScore}%
              </div>
            </article>
          )}
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-2">
            <p className="text-sm text-gray-500">
              Generate the PDF report for this audit.
            </p>
            {!exportReady && (
              <p className="text-xs text-red-600">
                Reason:{" "}
                {exportContract?.blocker_reasons?.[0]
                  ? toUserBlocker(exportContract.blocker_reasons[0])
                  : "Report export is temporarily unavailable."}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={generate}
              disabled={status === "generating" || !exportReady}
              className="btn-primary min-w-40"
            >
              {status === "generating" ? "Generating…" : "Generate PDF"}
            </button>
            {status === "ready" && (
              <button
                onClick={handleDownload}
                disabled={downloading}
                className="btn-secondary"
              >
                {downloading ? "Downloading..." : "Download PDF"}
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {report?.created_at && (
          <div className="mt-4 text-xs text-slate-500">
            Last generated: {new Date(report.created_at).toLocaleString()}
          </div>
        )}
      </header>

      <article className="surface-card p-7">
        <h2 className="text-base font-semibold text-slate-900">
          Export preview
        </h2>
        <div className="mt-4 grid gap-5 lg:grid-cols-2">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
              Top document-wide findings
            </h3>
            {documentFindings.length === 0 ? (
              <EmptyAchievement message="No document-wide findings in this dataset." />
            ) : (
              <ul className="mt-3 space-y-2 text-sm">
                {documentFindings.slice(0, 3).map((item) => (
                  <li
                    key={item.stable_ui_id}
                    className="rounded-xl border border-gray-200 bg-white p-3 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
                  >
                    <div className="font-semibold text-slate-900">
                      {item.title}
                    </div>
                    <div className="mt-0.5 text-gray-500">
                      {item.whyThisMatters}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
              Top section findings
            </h3>
            {sectionFindings.length === 0 ? (
              <EmptyAchievement message="No section findings in this dataset." />
            ) : (
              <ul className="mt-3 space-y-2 text-sm">
                {sectionFindings.slice(0, 3).map((item) => (
                  <li
                    key={item.stable_ui_id}
                    className="rounded-xl border border-gray-200 bg-white p-3 shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
                  >
                    <div className="font-semibold text-slate-900">
                      {item.sectionTitle}
                    </div>
                    <div className="mt-0.5 text-gray-500">
                      {item.primaryIssueLabel}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </article>
    </section>
  );
}

function metricTone(label: string): string {
  if (label === "Compliant")
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (label === "Partially compliant")
    return "border-amber-200 bg-amber-50 text-amber-700";
  if (label === "Non-compliant") return "border-red-200 bg-red-50 text-red-700";
  return "border-gray-200 bg-gray-50 text-gray-600";
}

function scoreMetricTone(score: number): string {
  if (score >= 80) return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (score >= 50) return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-red-200 bg-red-50 text-red-700";
}

function toUserBlocker(code: string): string {
  if (code === "final_findings_dataset_empty")
    return "No published findings for this audit.";
  return "Export is temporarily unavailable for this dataset.";
}

function EmptyAchievement({ message }: { message: string }) {
  return (
    <div className="mt-3 flex items-center gap-2.5 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-sm text-emerald-800">
      <svg
        className="h-5 w-5 shrink-0 text-emerald-600"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      {message}
    </div>
  );
}
