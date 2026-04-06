import { Link, NavLink } from 'react-router-dom'
import type { ReactNode } from 'react'

const nav = [
  { to: '/', label: 'Upload' },
  { to: '/sections', label: 'Sections' },
  { to: '/findings', label: 'Findings' },
  { to: '/report', label: 'Report' },
]

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-100 via-white to-slate-100 text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Link to="/" className="text-lg font-semibold tracking-wide">
            Compli<span className="text-cyan-600">Trace</span>
          </Link>
          <nav className="flex gap-2">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-lg px-4 py-2 text-sm transition ${
                    isActive ? 'bg-cyan-500/15 text-cyan-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  )
}
