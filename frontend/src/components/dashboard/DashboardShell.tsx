"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";
import Icon from "@/components/dashboard/Icon";

const navigation = [
  { label: "Overview", href: "/dashboard", icon: "grid" as const },
  { label: "Documents", href: "/dashboard/documents", icon: "files" as const },
];

const comingSoon = [
  { label: "AI Chat", icon: "sparkles" as const },
  { label: "Analytics", icon: "chart" as const },
  { label: "Settings", icon: "settings" as const },
];

function Brand() {
  return (
    <Link
      aria-label="KnowFlow AI dashboard"
      className="flex items-center gap-3 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-emerald-700"
      href="/dashboard"
    >
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-800 text-lg font-bold text-white shadow-sm shadow-emerald-950/10">
        K
      </span>
      <span className="min-w-0">
        <span className="block text-[15px] font-semibold tracking-tight text-slate-900">
          KnowFlow <span className="text-emerald-700">AI</span>
        </span>
        <span className="block text-[11px] font-medium tracking-wide text-slate-500">
          KNOWLEDGE WORKSPACE
        </span>
      </span>
    </Link>
  );
}

function NavigationLinks({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  return (
    <>
      {navigation.map((item) => {
        const active =
          item.href === "/dashboard"
            ? pathname === item.href
            : pathname.startsWith(item.href);
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`group flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 ${
              active
                ? "bg-emerald-50 text-emerald-800"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            } ${mobile ? "min-w-max" : ""}`}
            href={item.href}
            key={item.href}
          >
            <Icon
              className={`size-[18px] shrink-0 ${
                active ? "text-emerald-700" : "text-slate-400 group-hover:text-slate-600"
              }`}
              name={item.icon}
            />
            {item.label}
          </Link>
        );
      })}
      {!mobile && (
        <p className="mb-1 mt-8 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
          Workspace
        </p>
      )}
      {comingSoon.map((item) => (
        <span
          aria-disabled="true"
          className={`flex shrink-0 cursor-not-allowed items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-400 ${
            mobile ? "min-w-max" : ""
          }`}
          key={item.label}
          title={`${item.label} is coming soon`}
        >
          <Icon className="size-[18px] shrink-0" name={item.icon} />
          {item.label}
          <span
            className={`rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 ${
              mobile ? "ml-1" : "ml-auto"
            }`}
          >
            Soon
          </span>
        </span>
      ))}
    </>
  );
}

function NavigationFallback({ mobile = false }: { mobile?: boolean }) {
  return (
    <>
      {navigation.map((item) => (
        <Link
          className={`flex shrink-0 items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-600 ${
            mobile ? "min-w-max" : ""
          }`}
          href={item.href}
          key={item.href}
        >
          <Icon className="size-[18px] shrink-0 text-slate-400" name={item.icon} />
          {item.label}
        </Link>
      ))}
    </>
  );
}

export default function DashboardShell({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#f7f8f6] text-slate-900">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[258px] flex-col border-r border-slate-200/80 bg-white px-5 py-6 lg:flex">
        <Brand />
        <nav aria-label="Main navigation" className="mt-10 flex flex-col gap-1">
          <Suspense fallback={<NavigationFallback />}>
            <NavigationLinks />
          </Suspense>
        </nav>
        <div className="mt-auto rounded-2xl border border-emerald-100 bg-emerald-50/70 p-4">
          <div className="flex size-9 items-center justify-center rounded-xl bg-white text-emerald-700 shadow-sm">
            <Icon className="size-[18px]" name="layers" />
          </div>
          <p className="mt-3 text-sm font-semibold text-slate-800">
            Company knowledge, in flow
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Your team&apos;s information, in one thoughtful workspace.
          </p>
        </div>
      </aside>

      <div className="lg:pl-[258px]">
        <header className="sticky top-0 z-10 border-b border-slate-200/80 bg-white/95 backdrop-blur-md">
          <div className="flex h-[68px] items-center justify-between px-4 sm:px-7 lg:px-10">
            <div className="lg:hidden">
              <Brand />
            </div>
            <div className="hidden text-sm font-medium text-slate-500 lg:block">
              Company workspace
            </div>
            <Link
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 px-3.5 py-2 text-xs font-semibold text-slate-600 transition-colors hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
              href="/"
            >
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Back to home
            </Link>
          </div>
          <nav
            aria-label="Mobile navigation"
            className="flex gap-1 overflow-x-auto border-t border-slate-100 px-3 py-2 lg:hidden"
          >
            <Suspense fallback={<NavigationFallback mobile />}>
              <NavigationLinks mobile />
            </Suspense>
          </nav>
        </header>
        <main className="mx-auto w-full max-w-[1440px] px-4 py-7 sm:px-7 sm:py-9 lg:px-10 lg:py-10">
          {children}
        </main>
      </div>
    </div>
  );
}
