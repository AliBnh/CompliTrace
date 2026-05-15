import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useAppState } from "../../app/state";
import {
  getAnalysis,
  getAudit,
  getFindings,
  getReview,
  getSections,
} from "../../lib/api";
import {
  aggregateChecklistCounts,
  aggregateCounts,
  aggregateRawPublishedCounts,
  aggregateRawReviewFindingCounts,
  buildComplianceChecklist,
  buildFindingsPresentation,
  buildReviewSummary,
  severityDisplayForStatus,
  splitFindingsByScope,
  type ChecklistDisposition,
  type ComplianceChecklistRow,
  type NormalizedFinding,
} from "../../lib/presentation";
import type {
  AnalysisItemOut,
  PublishedFindingOut,
  ReviewItemOut,
  SectionOut,
} from "../../lib/types";

export function FindingsPage() {
  const { auditId, documentId } = useAppState();
  const [searchParams] = useSearchParams();
  const showDebug = searchParams.get("debug") === "true";
  const [findings, setFindings] = useState<PublishedFindingOut[]>([]);
  const [reviewItems, setReviewItems] = useState<ReviewItemOut[]>([]);
  const [analysisItems, setAnalysisItems] = useState<AnalysisItemOut[]>([]);
  const [sectionsById, setSectionsById] = useState<Record<string, SectionOut>>(
    {},
  );
  const [selectedByView, setSelectedByView] = useState<
    Record<"published" | "review" | "analysis", string | null>
  >({
    published: null,
    review: null,
    analysis: null,
  });
  const [viewMode, setViewMode] = useState<"published" | "review" | "analysis">(
    "published",
  );
  const [status, setStatus] = useState<string>("pending");
  const [complianceScore, setComplianceScore] = useState<number | null>(null);
  const [publishedError, setPublishedError] = useState<string | null>(null);
  const [selectedChecklistId, setSelectedChecklistId] = useState<string | null>(
    null,
  );

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
    const id = auditId;
    let cancelled = false;
    async function tick() {
      const audit = await getAudit(id);
      if (cancelled) return;
      setStatus(audit.status);
      setComplianceScore(audit.compliance_score ?? null);
      const [p, r, a] = await Promise.allSettled([
        getFindings(id),
        getReview(id),
        getAnalysis(id),
      ]);
      if (cancelled) return;
      if (p.status === "fulfilled") {
        setFindings(p.value);
        setPublishedError(null);
      } else {
        setFindings([]);
        setPublishedError("Published findings could not be loaded.");
      }
      setReviewItems(r.status === "fulfilled" ? r.value : []);
      setAnalysisItems(a.status === "fulfilled" ? a.value : []);
    }
    tick();
    const timer = setInterval(tick, 3500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [auditId]);

  const presentation = useMemo(
    () =>
      buildFindingsPresentation({
        publishedRows: findings,
        reviewRows: reviewItems,
        analysisRows: analysisItems,
        sectionsById,
        publishedBlocked:
          Boolean(publishedError) || status === "review_required",
      }),
    [
      findings,
      reviewItems,
      analysisItems,
      sectionsById,
      publishedError,
      status,
    ],
  );

  const activeRows =
    viewMode === "published"
      ? presentation.publishedVisibleFindings
      : viewMode === "review"
        ? presentation.reviewVisibleFindings
        : presentation.analysisVisibleFindings;
  const { sectionFindings } = useMemo(
    () => splitFindingsByScope(activeRows),
    [activeRows],
  );
  const documentSectionFindings = useMemo(
    () => activeRows.filter((r) => r.sectionId.startsWith("systemic:")),
    [activeRows],
  );

  const isPublishedBlockedView =
    viewMode === "published" && presentation.publishedBlocked;
  const showComplianceChecklist =
    viewMode === "published" &&
    findings.length === 0 &&
    status === "complete" &&
    !publishedError;

  const checklist = useMemo(
    () => buildComplianceChecklist(reviewItems),
    [reviewItems],
  );
  const checklistCounts = useMemo(
    () => aggregateChecklistCounts(checklist),
    [checklist],
  );
  const selectedChecklistRow =
    selectedChecklistId != null
      ? (checklist.find((r) => r.id === selectedChecklistId) ?? null)
      : null;

  // When the checklist is shown, published findings array is empty by definition.
  // Non-compliant must be 0 — review_block gaps are informational only, not published findings.
  // Any gap counts are moved into not_applicable so the total remains correct.
  const counts = showComplianceChecklist
    ? {
        ...checklistCounts,
        non_compliant: 0,
        not_applicable:
          checklistCounts.not_applicable + checklistCounts.non_compliant,
      }
    : viewMode === "published"
      ? aggregateRawPublishedCounts(findings)
      : viewMode === "review"
        ? aggregateRawReviewFindingCounts(reviewItems)
        : aggregateCounts(activeRows);
  const reviewSummary = buildReviewSummary(presentation.reviewVisibleFindings);

  useEffect(() => {
    setSelectedByView((current) => {
      const existing = current[viewMode];
      if (existing && activeRows.some((row) => row.stable_ui_id === existing))
        return current;
      if (!sectionFindings.length) return { ...current, [viewMode]: null };
      return { ...current, [viewMode]: sectionFindings[0].stable_ui_id };
    });
  }, [activeRows, viewMode]);

  if (!auditId)
    return (
      <EmptyState message="No audit in progress. Trigger an audit from Sections page." />
    );

  const selected =
    activeRows.find((x) => x.stable_ui_id === selectedByView[viewMode]) ?? null;

  return (
    <section className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="space-y-4">
        <header className="surface-card p-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="section-title">Findings workspace</h1>
              <p className="section-subtitle">
                Audit status:{" "}
                <span className="font-medium text-slate-700 capitalize">
                  {status}
                </span>
              </p>
            </div>
            {status === "complete" && complianceScore !== null && (
              <div
                className={`inline-flex items-center gap-3 rounded-lg border px-3 py-2 ${complianceScoreClass(complianceScore)}`}
              >
                <div className="text-[11px] font-semibold uppercase tracking-widest opacity-80">
                  Score
                </div>
                <div className="text-2xl font-bold tabular-nums leading-none">
                  {complianceScore}%
                </div>
              </div>
            )}
          </div>

          {status === "complete" &&
            complianceScore !== null &&
            complianceScore < 100 && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-600">
                    Next step
                  </div>
                  <div className="mt-0.5 text-sm font-medium text-slate-800">
                    Review the remediation plan for prioritized fixes.
                  </div>
                </div>
                <Link to="/remediation" className="btn-secondary">
                  View remediation
                </Link>
              </div>
            )}

          {showDebug && (
            <div className="mt-4 flex flex-wrap gap-2">
              {(["published", "review", "analysis"] as const).map((mode) => (
                <button
                  key={mode}
                  className={`rounded-lg px-4 py-1.5 text-xs font-semibold transition-colors duration-150 ${
                    viewMode === mode
                      ? "bg-blue-600 text-white shadow-sm"
                      : "border border-gray-200 bg-white text-slate-600 hover:bg-gray-50 hover:text-slate-900"
                  }`}
                  onClick={() => setViewMode(mode)}
                >
                  {mode === "published"
                    ? "Findings"
                    : mode === "review"
                      ? "Review"
                      : "Analysis"}
                </button>
              ))}
            </div>
          )}

          <p className="mt-3 text-xs text-gray-500">
            {viewMode === "published" && ""}
            {viewMode === "review" &&
              "Complete audit triage view showing all assessed obligations, including gaps, compliant areas, and items needing further review."}
            {viewMode === "analysis" &&
              "Internal pipeline diagnostics. Not for reporting — use Findings or Review tabs for audit output."}
          </p>

          {presentation.publishedBlocked && viewMode === "published" && (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              Final findings are blocked while review is in progress.
            </div>
          )}
          {viewMode === "review" && reviewSummary && (
            <div className="mt-3 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
              {reviewSummary}
            </div>
          )}

          {!isPublishedBlockedView && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white">
              <div className="grid grid-cols-2 gap-px bg-slate-200 sm:grid-cols-5">
                {[
                  ["Compliant", counts.compliant],
                  ["Partially", counts.partially_compliant],
                  ["Non-compliant", counts.non_compliant],
                  ["Not applicable", counts.not_applicable],
                  ["Total", counts.total],
                ].map(([label, value]) => (
                  <div
                    key={String(label)}
                    className="bg-white px-3 py-3 min-w-0 text-center flex flex-col items-center justify-center min-h-24"
                  >
                    <div className="h-6 text-[10px] font-semibold uppercase tracking-widest text-slate-500 line-clamp-1 flex items-center">
                      {label}
                    </div>
                    <div className="mt-2 text-2xl font-bold tabular-nums text-slate-900">
                      {value}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {viewMode === "review" && counts.total > 0 && (
            <p className="mt-2 text-xs text-gray-400">
              The review dataset may include additional items that are
              consolidated before final publication.
            </p>
          )}
        </header>

        {viewMode === "analysis" && (
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-3.5 text-sm text-slate-600">
            This tab shows internal pipeline diagnostics from the audit engine.
            These are working artifacts used to produce the published findings —
            they are not compliance conclusions. Use the Published or Review
            tabs for actionable output.
          </div>
        )}

        {showComplianceChecklist && (
          <ComplianceChecklist
            rows={checklist}
            selectedId={selectedChecklistId}
            onSelect={setSelectedChecklistId}
          />
        )}

        {!showComplianceChecklist && !isPublishedBlockedView && (
          <div className="surface-card p-5">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500">
              Document-wide findings
            </h2>
            {documentSectionFindings.length === 0 ? (
              <EmptyInlineState message="Excellent result. No document-wide findings were detected in this view." />
            ) : (
              <div className="mt-3 space-y-2">
                {documentSectionFindings.map((finding) => (
                  <article
                    key={finding.stable_ui_id}
                    onClick={() =>
                      setSelectedByView((c) => ({
                        ...c,
                        [viewMode]: finding.stable_ui_id,
                      }))
                    }
                    className={`cursor-pointer rounded-lg border border-slate-200 bg-white p-4 text-sm transition-colors ${severityBorderClass(finding.overallSeverity)} ${
                      selected?.stable_ui_id === finding.stable_ui_id
                        ? "border-blue-300 bg-blue-50/40"
                        : "hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold text-slate-900">
                      {finding.primaryIssueLabel}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                        Entire document
                      </span>
                      <FindingStatus status={finding.overallStatus} />
                      <SeverityPill severity={finding.overallSeverity} />
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        )}

        {!showComplianceChecklist && !isPublishedBlockedView && (
          <div className="surface-card overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 text-left text-xs font-semibold uppercase tracking-widest text-gray-500">
                <tr>
                  <th className="px-4 py-3">Section</th>
                  <th className="px-4 py-3">Issues</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Severity</th>
                </tr>
              </thead>
              <tbody>
                {sectionFindings.length === 0 ? (
                  <tr>
                    <td className="px-4 py-8" colSpan={4}>
                      <EmptyInlineState
                        message={
                          viewMode === "published"
                            ? "Excellent result. No published findings for this audit."
                            : "No section findings in this dataset."
                        }
                      />
                    </td>
                  </tr>
                ) : (
                  sectionFindings.map((finding, index) => (
                    <tr
                      key={finding.stable_ui_id}
                      onClick={() =>
                        setSelectedByView((c) => ({
                          ...c,
                          [viewMode]: finding.stable_ui_id,
                        }))
                      }
                      className={`cursor-pointer border-t border-gray-100 transition-colors ${severityRowClass(finding.overallSeverity)} ${
                        selected?.stable_ui_id === finding.stable_ui_id
                          ? "bg-blue-50"
                          : index % 2 === 0
                            ? "bg-white hover:bg-gray-50/60"
                            : "bg-gray-50/40 hover:bg-gray-50/80"
                      }`}
                    >
                      <td className="px-4 py-3">{finding.sectionTitle}</td>
                      <td className="px-4 py-3 text-slate-700">
                        {finding.primaryIssueLabel}
                        {finding.issueCount > 1 ? (
                          <span className="ml-1 text-xs text-gray-400">
                            (+{finding.issueCount - 1})
                          </span>
                        ) : (
                          ""
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <FindingStatus status={finding.overallStatus} />
                      </td>
                      <td className="px-4 py-3">
                        <SeverityIndicator
                          severity={severityDisplayForStatus(
                            finding.overallStatus,
                            finding.overallSeverity,
                          )}
                        />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <aside className="surface-card sticky top-24 h-fit overflow-hidden">
        <div className="border-b border-slate-200 bg-slate-50 px-6 py-4">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
            Detail panel
          </h2>
        </div>
        <div className="p-6">
          {showComplianceChecklist ? (
            selectedChecklistRow ? (
              <ChecklistDetail row={selectedChecklistRow} />
            ) : (
              <EmptyDetailPanel message="Click any checklist row for the full assessment detail." />
            )
          ) : !selected || isPublishedBlockedView ? (
            <EmptyDetailPanel message="Select a finding to view details." />
          ) : (
            <FindingDetail finding={selected} />
          )}
        </div>
      </aside>
    </section>
  );
}

function FindingDetail({ finding }: { finding: NormalizedFinding }) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">
          {finding.sectionTitle}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <FindingStatus status={finding.overallStatus} />
          {severityDisplayForStatus(
            finding.overallStatus,
            finding.overallSeverity,
          ) && <SeverityPill severity={finding.overallSeverity} />}
        </div>
      </div>

      <div className="space-y-2">
        <Detail
          label="Scope"
          value={
            finding.scope === "Document-wide"
              ? "Entire document"
              : finding.sectionTitle
          }
        />
      </div>

      {finding.issues.map((issue) => (
        <div
          key={`${finding.stable_ui_id}:${issue.issueKey}`}
          className="rounded-xl border border-gray-200 bg-white overflow-hidden"
        >
          <div className="border-b border-gray-100 bg-gray-50 px-4 py-2.5">
            <span className="text-xs font-semibold uppercase tracking-widest text-gray-500">
              Finding
            </span>
            <p className="mt-0.5 text-sm font-semibold text-slate-900">
              {issue.issueLabel}
            </p>
          </div>
          <div className="divide-y divide-gray-100 p-0">
            <DetailInline
              label="Why this matters"
              value={issue.whyThisMatters}
            />
            <DetailInline
              label="Recommended action"
              value={issue.recommendedAction}
            />
            {!!issue.legalAnchors.length && (
              <DetailInline
                label="GDPR requirement"
                value={issue.legalAnchors.join(", ")}
              />
            )}
            <DetailInline
              label="Evidence from notice"
              value={issue.evidenceText}
            />
            {!!issue.omissionStatement && (
              <DetailInline
                label="Missing disclosure"
                value={issue.omissionStatement}
              />
            )}
            {issue.citations.length > 0 && (
              <div className="bg-gray-50 px-4 py-3">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
                  Citations
                </h3>
                <ul className="mt-2 space-y-2">
                  {issue.citations.map((citation, idx) => (
                    <li
                      key={`${finding.stable_ui_id}:${issue.issueKey}:citation:${idx}`}
                      className="rounded-lg border border-gray-200 bg-white p-2.5 text-sm"
                    >
                      <div className="font-medium text-slate-800">
                        {citation.source_section_title}
                      </div>
                      <div className="mt-0.5 text-slate-600">
                        {citation.excerpt_text}
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        {citation.gdpr_articles.join(", ")}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-block">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
        {label}
      </h3>
      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-700">{value}</p>
    </div>
  );
}

function DetailInline({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-5 py-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-slate-500">
        {label}
      </h3>
      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-800">
        {formatUiValue(label, value)}
      </p>
    </div>
  );
}

function ComplianceChecklist({
  rows,
  selectedId,
  onSelect,
}: {
  rows: ComplianceChecklistRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="surface-card overflow-hidden">
      <div className="border-b border-gray-200 bg-gray-50 px-5 py-4">
        <h2 className="text-sm font-semibold text-slate-900">
          GDPR obligation checklist
        </h2>
        <p className="mt-1 text-sm text-gray-500">
          No compliance gaps were identified in this document. The checklist
          below shows every GDPR transparency obligation we assessed and its
          outcome.
        </p>
      </div>
      <div className="divide-y divide-gray-100">
        {rows.map((row) => (
          <div
            key={row.id}
            onClick={() => onSelect(row.id)}
            className={`cursor-pointer px-5 py-3 transition-colors ${checklistRowAccent(row.disposition)} ${
              selectedId === row.id ? "bg-blue-50" : "hover:bg-gray-50"
            }`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span className="font-medium text-slate-900 text-sm">
                {row.label}
              </span>
              <ChecklistBadge disposition={row.disposition} />
            </div>
            <p className="mt-1 text-xs text-gray-500 leading-relaxed">
              {row.reason}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChecklistDetail({ row }: { row: ComplianceChecklistRow }) {
  if (row.disposition === "not_assessable")
    return <NotApplicableDetail row={row} />;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">{row.label}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <ChecklistBadge disposition={row.disposition} />
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="border-b border-gray-100 bg-gray-50 px-4 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-widest text-gray-500">
            Obligation assessment
          </span>
          <p className="mt-0.5 text-sm font-semibold text-slate-900">
            {row.label}
          </p>
        </div>
        <div className="divide-y divide-gray-100">
          <DetailInline label="System assessment" value={row.reason} />
          {row.source_scope_dependency && (
            <DetailInline
              label="Scope note"
              value={row.source_scope_dependency}
            />
          )}
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
        <p className="text-xs text-slate-600 leading-relaxed">
          This assessment is produced by the audit engine based on its review of
          the full document. It reflects whether this GDPR transparency
          obligation was found to be satisfied, not applicable, or presenting a
          gap — without rising to the level of a published finding.
        </p>
      </div>
    </div>
  );
}

function NotApplicableDetail({ row }: { row: ComplianceChecklistRow }) {
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">{row.label}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <ChecklistBadge disposition={row.disposition} />
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        <div className="border-b border-gray-100 bg-gray-50 px-4 py-2.5">
          <span className="text-xs font-semibold uppercase tracking-widest text-gray-500">
            Why this is not applicable
          </span>
        </div>
        <div className="divide-y divide-gray-100">
          <div className="px-4 py-3">
            <p className="text-sm leading-relaxed text-slate-700">
              This obligation was not triggered because no signals relevant to
              it were found in this document. The system determined it does not
              apply to this document's content. This is not a gap — it means the
              obligation is not relevant here.
            </p>
          </div>
          <DetailInline label="System note" value={row.reason} />
          {row.source_scope_dependency && (
            <DetailInline
              label="Scope note"
              value={row.source_scope_dependency}
            />
          )}
        </div>
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
        <p className="text-xs text-gray-500 leading-relaxed">
          If you believe this obligation should apply to this document, review
          the relevant sections manually.
        </p>
      </div>
    </div>
  );
}

function ChecklistBadge({
  disposition,
}: {
  disposition: ChecklistDisposition;
}) {
  if (disposition === "satisfied")
    return (
      <span className="inline-flex h-6 shrink-0 items-center gap-1 rounded-full bg-emerald-600 px-3 text-xs font-semibold text-white">
        <svg
          className="h-4 w-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4.5 12.75l6 6 9-13.5"
          />
        </svg>
        Compliant
      </span>
    );
  if (disposition === "gap")
    return (
      <span className="inline-flex shrink-0 items-center rounded-full border border-red-400 px-2.5 py-0.5 text-xs font-medium text-red-600">
        Gap identified
      </span>
    );
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500">
      Not applicable
    </span>
  );
}

function FindingStatus({ status }: { status: string }) {
  if (status === "Compliant") {
    return (
      <span className="inline-flex h-6 min-w-[8rem] items-center justify-center gap-1 rounded-full bg-emerald-600 px-3 text-xs font-semibold text-white whitespace-nowrap">
        <svg
          className="h-4 w-4"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4.5 12.75l6 6 9-13.5"
          />
        </svg>
        Compliant
      </span>
    );
  }
  const cls =
    status === "Non-compliant"
      ? "border-red-200 bg-red-50 text-red-700"
      : status === "Partially compliant"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : "border-gray-200 bg-gray-100 text-gray-600";
  return (
    <span
      className={`inline-flex h-6 min-w-[8rem] items-center justify-center rounded-full border px-3 text-xs font-semibold whitespace-nowrap ${cls}`}
    >
      {status}
    </span>
  );
}

function SeverityIndicator({
  severity,
}: {
  severity: string | null | undefined;
}) {
  if (!severity) return <span className="text-gray-400">—</span>;
  const dot =
    severity === "High"
      ? "bg-red-500"
      : severity === "Medium"
        ? "bg-amber-500"
        : "bg-gray-400";
  const text =
    severity === "High"
      ? "text-red-600"
      : severity === "Medium"
        ? "text-amber-600"
        : "text-gray-500";
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-medium ${text}`}
    >
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      {severity}
    </span>
  );
}

function SeverityPill({ severity }: { severity: string | null | undefined }) {
  if (!severity) return null;
  const cls =
    severity === "High"
      ? "border-red-200 bg-red-50 text-red-700"
      : severity === "Medium"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : "border-gray-200 bg-gray-100 text-gray-600";
  return (
    <span
      className={`inline-flex h-6 items-center rounded-full border px-3 text-xs font-semibold ${cls}`}
    >
      Severity: {severity}
    </span>
  );
}

function EmptyDetailPanel({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
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
          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
        />
      </svg>
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );
}

function EmptyInlineState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <div className="mb-2 grid h-9 w-9 place-items-center rounded-full bg-emerald-100 text-emerald-600">
        <svg
          className="h-5 w-5"
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
      </div>
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );
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
          d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
        />
      </svg>
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );
}

function complianceScoreClass(score: number): string {
  if (score >= 80) return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (score >= 50) return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-red-200 bg-red-50 text-red-700";
}

function severityBorderClass(severity: string | null | undefined): string {
  if (severity === "High") return "border-l-4 border-l-red-500";
  if (severity === "Medium") return "border-l-4 border-l-amber-500";
  if (severity === "Low") return "border-l-4 border-l-gray-400";
  return "border-l-4 border-l-transparent";
}

function severityRowClass(severity: string | null | undefined): string {
  if (severity === "High") return "border-l-[3px] border-l-red-500";
  if (severity === "Medium") return "border-l-[3px] border-l-amber-500";
  if (severity === "Low") return "border-l-[3px] border-l-gray-400";
  return "border-l-[3px] border-l-transparent";
}

function checklistRowAccent(disposition: ChecklistDisposition): string {
  if (disposition === "satisfied") return "border-l-2 border-l-emerald-500";
  if (disposition === "gap") return "border-l-2 border-l-red-500";
  return "";
}

function formatUiValue(label: string, value: string): string {
  const trimmed = value.trim();
  if (
    label.toLowerCase() === "scope note" &&
    /^(high|medium|low)$/.test(trimmed.toLowerCase())
  ) {
    return trimmed.charAt(0).toUpperCase() + trimmed.slice(1).toLowerCase();
  }
  return trimmed.replace(/\b([a-z])([a-z_]{2,})\b/g, (match, first, rest) => {
    if (match.includes("_")) return match.replace(/_/g, " ");
    return `${first}${rest}`;
  });
}
