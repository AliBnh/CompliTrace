import { Link, NavLink, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAppState } from "../app/state";
import { DocumentSidebar } from "./DocumentSidebar";
import { LogOut, FileCheck } from "lucide-react";

const nav = [
  { to: "/", label: "Upload", cue: "1" },
  { to: "/sections", label: "Sections", cue: "2" },
  { to: "/findings", label: "Findings", cue: "3" },
  { to: "/remediation", label: "Remediation", cue: "4" },
  { to: "/report", label: "Report", cue: "5" },
];

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { user, signOut } = useAppState();
  const activeStep = Math.max(
    nav.findIndex((item) => item.to === location.pathname),
    0,
  );

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-900">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/92 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1320px] flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <Link to="/" className="flex items-center gap-2">
              <FileCheck className="h-6 w-6 text-blue-600" />
              <span className="text-2xl font-bold tracking-tight text-slate-900">
                Compli
                <span className="bg-gradient-to-r from-sky-500 to-blue-700 bg-clip-text text-transparent">
                  Trace
                </span>
              </span>
            </Link>
          </div>

          <div className="flex items-center gap-3">
            <nav className="flex items-center gap-1 rounded-full border border-slate-200 bg-white p-1 shadow-sm">
              {nav.map((item, index) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition ${
                      isActive
                        ? "bg-gradient-to-r from-sky-500 to-blue-600 text-white shadow-md shadow-blue-200/50"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                    }`
                  }
                >
                  <span
                    className={`grid h-5 w-5 place-items-center rounded-full text-[10px] ${activeStep >= index ? "bg-white/20" : "bg-slate-200 text-slate-500"}`}
                  >
                    {item.cue}
                  </span>
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="flex items-center gap-3 rounded-full border border-slate-200 bg-white px-3 py-2 shadow-sm">
              <div className="leading-tight">
                <div className="text-sm font-semibold text-slate-800">
                  {user ? `${user.first_name} ${user.last_name}` : "User"}
                </div>
                <div className="text-[11px] text-slate-500">
                  {user?.organization_name ?? ""}
                </div>
              </div>
              <div className="h-6 w-px bg-slate-200" />
              <button
                onClick={signOut}
                className="rounded-full p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
                title="Logout"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </header>
      <div className="mx-auto flex max-w-[1320px]">
        <DocumentSidebar />
        <main className="min-w-0 flex-1 px-6 py-8">{children}</main>
      </div>
    </div>
  );
}
