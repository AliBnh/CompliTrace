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
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 shadow-sm backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <Link to="/" className="text-xl font-bold tracking-wide">
            Compli<span className="bg-gradient-to-r from-cyan-600 to-blue-700 bg-clip-text text-transparent">Trace</span>
          </Link>
          <nav className="flex gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-1">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-xl px-5 py-2.5 text-base font-medium transition ${
                    isActive
                      ? 'bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow'
                      : 'text-slate-600 hover:bg-white hover:text-slate-900'
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
