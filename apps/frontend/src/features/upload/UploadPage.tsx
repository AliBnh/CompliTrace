import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAppState } from "../../app/state";
import { createGroup, getGroups, uploadDocument } from "../../lib/api";
import type { GroupOut } from "../../lib/types";
import { FileUp, Workflow } from "lucide-react";

export function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [groups, setGroups] = useState<GroupOut[]>([]);
  const [groupInput, setGroupInput] = useState("");
  const [groupMenuOpen, setGroupMenuOpen] = useState(false);
  const navigate = useNavigate();
  const { setDocumentId, setAuditId, selectedGroupId, setSelectedGroupId } =
    useAppState();

  useEffect(() => {
    getGroups()
      .then(setGroups)
      .catch(() => setGroups([]));
  }, []);

  const selectedGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupId) ?? null,
    [groups, selectedGroupId],
  );
  const predictedVersion = selectedGroup ? selectedGroup.versions.length : null;
  const matchingGroup = useMemo(
    () =>
      groups.find(
        (group) => group.name.toLowerCase() === groupInput.trim().toLowerCase(),
      ) ?? null,
    [groups, groupInput],
  );
  const filteredGroups = useMemo(
    () =>
      groups
        .filter((group) =>
          group.name.toLowerCase().includes(groupInput.trim().toLowerCase()),
        )
        .slice(0, 8),
    [groups, groupInput],
  );

  async function onUpload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setProgress(0);
    try {
      let activeGroupId = selectedGroupId;
      if (groupInput.trim() && !matchingGroup) {
        const created = await createGroup(groupInput.trim());
        activeGroupId = created.id;
        setSelectedGroupId(created.id);
        setGroups((prev) => [created, ...prev]);
      } else if (matchingGroup) {
        activeGroupId = matchingGroup.id;
        setSelectedGroupId(matchingGroup.id);
      }
      const doc = await uploadDocument(file, setProgress);
      setDocumentId(doc.id);
      setAuditId(null);
      if (!activeGroupId && !groupInput.trim()) setSelectedGroupId(null);
      navigate("/sections");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="grid gap-6 xl:grid-cols-[1.45fr_1fr]">
      <article className="surface-card animate-rise p-7">
        <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="section-title">Upload policy document</h1>
            <p className="section-subtitle">
              Start by adding a policy PDF. We extract sections and
              automatically prepare your GDPR compliance audit workspace.
            </p>
          </div>
          <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">
            Step 1 of 5
          </span>
        </div>

        <label className="group block cursor-pointer rounded-lg border border-dashed border-slate-300 bg-slate-50 p-9 text-center transition-all duration-150 hover:border-blue-400 hover:bg-blue-50/30">
          <input
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-full border border-slate-200 bg-white shadow-sm">
            <FileUp className="h-6 w-6 text-slate-400 transition-colors group-hover:text-blue-600" />
          </div>
          <p className="text-sm font-semibold text-slate-800">
            Choose a policy PDF (up to 20 MB)
          </p>
          <p className="mt-1 text-xs text-gray-500">
            Click to browse your files securely.
          </p>
          <p className="mt-3 truncate text-sm font-medium text-blue-600">
            {file?.name ?? "No file selected yet"}
          </p>
        </label>

        <div className="relative mt-5 space-y-2">
          <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">
            Document Group
          </label>
          <input
            value={groupInput}
            onFocus={() => setGroupMenuOpen(true)}
            onChange={(e) => {
              const value = e.target.value;
              setGroupInput(value);
              setGroupMenuOpen(true);
              const group = groups.find(
                (g) => g.name.toLowerCase() === value.trim().toLowerCase(),
              );
              setSelectedGroupId(group?.id ?? null);
            }}
            onBlur={() => setTimeout(() => setGroupMenuOpen(false), 120)}
            placeholder="Select or type group name..."
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          />
          {groupMenuOpen && (
            <div className="absolute left-0 right-0 top-[70px] z-20 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
              {filteredGroups.length > 0 ? (
                <ul className="max-h-52 overflow-y-auto p-1.5">
                  {filteredGroups.map((group) => (
                    <li key={group.id}>
                      <button
                        type="button"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setGroupInput(group.name);
                          setSelectedGroupId(group.id);
                          setGroupMenuOpen(false);
                        }}
                        className="w-full rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                      >
                        {group.name}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="px-3 py-2.5 text-sm text-slate-500">
                  No matching groups
                </div>
              )}
            </div>
          )}
          {groupInput.trim() && !matchingGroup && (
            <p className="text-xs text-sky-700">
              Create group: "{groupInput.trim()}"
            </p>
          )}
          {selectedGroup && (
            <p className="text-xs text-gray-500">
              This will be saved as v{predictedVersion}
            </p>
          )}
        </div>

        {loading && (
          <div className="detail-block mt-6">
            <div className="mb-2 flex items-center justify-between text-sm text-slate-600">
              <span>Uploading and parsing</span>
              <span className="font-semibold text-slate-700">{progress}%</span>
            </div>
            <div className="h-2 rounded-full bg-gray-200">
              <div
                className="h-full rounded-full bg-blue-600 transition-all duration-500"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="mt-7 flex flex-wrap items-center gap-3">
          <button
            onClick={onUpload}
            disabled={!file || loading}
            className="btn-primary min-w-40"
          >
            {loading ? "Uploading…" : "Upload & parse"}
          </button>
          <span className="inline-flex min-h-[40px] items-center text-xs text-gray-500">
            PDF content remains associated with this audit workflow.
          </span>
        </div>
      </article>

      <aside className="surface-card animate-rise p-6">
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4 text-slate-400" />
          <h2 className="text-base font-semibold text-slate-900">
            Guided workflow
          </h2>
        </div>
        <p className="mt-1 text-sm text-gray-500">
          Each stage keeps the legal review focused and auditable.
        </p>
        <ol className="mt-5 space-y-3">
          {[
            {
              title: "Upload policy PDF",
              desc: "Create a document record and parse sections.",
            },
            {
              title: "Review sections",
              desc: "Verify extraction quality before analysis.",
            },
            {
              title: "Inspect findings",
              desc: "Navigate published, review, and analysis layers.",
            },
            {
              title: "Remediation",
              desc: "Generate and apply clause fixes where needed.",
            },
            {
              title: "Export report",
              desc: "Generate an executive PDF with audit metrics.",
            },
          ].map((step, index) => (
            <li
              key={step.title}
              className="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3"
            >
              <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
                {index + 1}
              </span>
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  {step.title}
                </p>
                <p className="text-xs text-gray-500">{step.desc}</p>
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </section>
  );
}
