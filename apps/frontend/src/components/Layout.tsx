import { Link, NavLink, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'

const nav = [
  { to: '/', label: 'Upload', cue: '1' },
  { to: '/sections', label: 'Sections', cue: '2' },
  { to: '/findings', label: 'Findings', cue: '3' },
  { to: '/report', label: 'Report', cue: '4' },
]

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const activeStep = Math.max(nav.findIndex((item) => item.to === location.pathname), 0)

  return (
    <div className="min-h-screen text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200/70 bg-white/78 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <Link to="/" className="text-2xl font-bold tracking-tight text-slate-900">
              Compli<span className="bg-gradient-to-r from-sky-500 to-blue-700 bg-clip-text text-transparent">Trace</span>
            </Link>
            <p className="text-xs text-slate-500">GDPR audit workspace for legal & compliance teams</p>
          </div>

          <nav className="glass-panel flex items-center gap-1 p-1.5 shadow-sm">
            {nav.map((item, index) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition duration-200 ${
                    isActive
                      ? 'bg-gradient-to-r from-sky-500 to-blue-600 text-white shadow-md shadow-blue-200/50'
                      : 'text-slate-600 hover:bg-white hover:text-slate-900'
                  }`
                }
              >
                <span className={`grid h-5 w-5 place-items-center rounded-full text-[10px] ${activeStep >= index ? 'bg-white/25' : 'bg-slate-200 text-slate-500'}`}>{item.cue}</span>
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
