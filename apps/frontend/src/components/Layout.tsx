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
    <div className="min-h-screen text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <Link to="/" className="text-2xl font-bold tracking-tight">
            Compli<span className="bg-gradient-to-r from-sky-500 to-blue-700 bg-clip-text text-transparent">Trace</span>
          </Link>
          <nav className="glass-panel flex gap-1 p-1.5 shadow-sm">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-xl px-5 py-2.5 text-base font-medium transition duration-200 ${
                    isActive
                      ? 'bg-gradient-to-r from-sky-500 to-blue-600 text-white shadow-md shadow-blue-200/50'
                      : 'text-slate-600 hover:bg-white/90 hover:text-slate-900'
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
