import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAppState } from '../app/state'
import { createGroup, deleteGroup, getAudit, getDocument, getGroups, renameGroup } from '../lib/api'
import type { GroupOut } from '../lib/types'
import { ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from 'lucide-react'

function scoreBadge(score: number | null | undefined) {
  if (score == null) return 'border-gray-200 bg-gray-100 text-gray-500'
  if (score >= 80) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (score >= 50) return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-red-200 bg-red-50 text-red-700'
}

function truncate(text: string, max = 28) {
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

export function DocumentSidebar() {
  const navigate = useNavigate()
  const { auditId, setAuditId, setDocumentId, setSelectedGroupId } = useAppState()
  const [groups, setGroups] = useState<GroupOut[]>([])
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [newGroup, setNewGroup] = useState('')
  const [polling, setPolling] = useState(false)
  const [documentTitles, setDocumentTitles] = useState<Record<string, string>>({})

  async function refreshGroups() {
    const data = await getGroups()
    setGroups(data)
    setExpanded((prev) => {
      const next = { ...prev }
      for (const group of data) {
        if (next[group.id] == null) next[group.id] = true
      }
      return next
    })
  }

  useEffect(() => {
    refreshGroups().catch(() => setGroups([]))
  }, [])

  useEffect(() => {
    if (!auditId) {
      setPolling(false)
      return
    }
    let active = true
    getAudit(auditId)
      .then((audit) => {
        if (!active) return
        setPolling(audit.status === 'running' || audit.status === 'pending')
      })
      .catch(() => setPolling(false))
    return () => {
      active = false
    }
  }, [auditId])

  useEffect(() => {
    if (!polling) return
    const timer = setInterval(() => {
      refreshGroups().catch(() => undefined)
    }, 10000)
    return () => clearInterval(timer)
  }, [polling])

  useEffect(() => {
    const docIds = Array.from(new Set(groups.flatMap((g) => g.versions.map((v) => v.document_id))))
    if (!docIds.length) return
    let active = true
    Promise.all(
      docIds.map(async (id) => {
        try {
          const doc = await getDocument(id)
          return [id, doc.title] as const
        } catch {
          return [id, id] as const
        }
      }),
    ).then((pairs) => {
      if (!active) return
      setDocumentTitles(Object.fromEntries(pairs))
    })
    return () => {
      active = false
    }
  }, [groups])

  const sortedGroups = useMemo(
    () => [...groups].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
    [groups],
  )

  async function onCreateGroup() {
    if (!newGroup.trim()) return
    await createGroup(newGroup.trim())
    setNewGroup('')
    await refreshGroups()
  }

  async function onRename(groupId: string) {
    if (!renameValue.trim()) return
    await renameGroup(groupId, renameValue.trim())
    setRenaming(null)
    await refreshGroups()
  }

  async function onDelete(groupId: string) {
    if (!window.confirm('Delete this group? Existing audits/documents will be kept.')) return
    await deleteGroup(groupId)
    await refreshGroups()
  }

  return (
    <aside className="h-[calc(100vh-72px)] w-[260px] shrink-0 overflow-y-auto border-r border-slate-200 bg-slate-50/80 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">My Documents</h2>
        <button
          onClick={onCreateGroup}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
        >
          <Plus className="h-3.5 w-3.5" />
          New
        </button>
      </div>
      <input
        value={newGroup}
        onChange={(e) => setNewGroup(e.target.value)}
        placeholder="Group name..."
        className="mb-3 w-full rounded-md border border-slate-200 bg-white px-2.5 py-2 text-xs outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
      />
      {sortedGroups.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-200 p-2 text-xs text-slate-500">
          No document groups yet. Upload a document to get started.
        </p>
      ) : (
        <div className="space-y-2.5">
          {sortedGroups.map((group) => (
            <div key={group.id} className="rounded-lg border border-slate-200/70 bg-white">
              <div className="group flex items-center justify-between px-2.5 py-2">
                <button
                  onClick={() => setExpanded((v) => ({ ...v, [group.id]: !v[group.id] }))}
                  className="truncate text-left text-xs font-semibold leading-5 text-slate-700"
                  title={group.name}
                >
                  <span className="inline-flex items-center gap-1.5">
                    {expanded[group.id] ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
                    {truncate(group.name, 22)}
                  </span>
                </button>
                <div className="flex items-center gap-1.5">
                  <span className={`inline-flex h-5 w-12 items-center justify-center rounded-full border text-[10px] font-semibold tabular-nums ${scoreBadge(group.latest_compliance_score)}`}>
                    {group.latest_compliance_score == null ? '—' : `${group.latest_compliance_score}%`}
                  </span>
                  <button
                    onClick={() => {
                      setRenaming(group.id)
                      setRenameValue(group.name)
                    }}
                    className="rounded p-1 text-slate-500 opacity-0 transition hover:bg-slate-100 hover:opacity-100 group-hover:opacity-100"
                    title="Rename group"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    onClick={() => onDelete(group.id)}
                    className="rounded p-1 text-slate-500 opacity-0 transition hover:bg-slate-100 hover:opacity-100 group-hover:opacity-100"
                    title="Delete group"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              {renaming === group.id && (
                <div className="px-2 pb-2">
                  <input
                    autoFocus
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onBlur={() => onRename(group.id).catch(() => undefined)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') onRename(group.id).catch(() => undefined)
                    }}
                    className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-2 text-xs outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  />
                </div>
              )}
              {expanded[group.id] && (
                <ul className="space-y-1 border-t border-slate-100 p-2">
                  {group.versions.map((version) => (
                    <li key={version.audit_id}>
                      <button
                        onClick={() => {
                          setSelectedGroupId(group.id)
                          setAuditId(version.audit_id)
                          setDocumentId(version.document_id)
                          navigate('/findings')
                        }}
                        className={`flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs leading-5 ${
                          auditId === version.audit_id ? 'bg-sky-50 text-sky-700' : 'hover:bg-slate-50'
                        }`}
                      >
                        <span className="truncate" title={documentTitles[version.document_id] ?? version.document_id}>
                          v{version.version_number} - {truncate(documentTitles[version.document_id] ?? version.document_id, 24)}
                        </span>
                        <span className={`inline-flex h-5 w-12 items-center justify-center rounded-full border text-[10px] font-semibold tabular-nums ${scoreBadge(version.compliance_score)}`}>
                          {version.compliance_score == null ? '—' : `${version.compliance_score}%`}
                        </span>
                      </button>
                    </li>
                  ))}
                  {group.versions.length === 0 && (
                    <li className="rounded px-2 py-1 text-[11px] text-slate-400">No versions yet</li>
                  )}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </aside>
  )
}
