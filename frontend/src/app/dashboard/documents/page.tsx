import { Suspense } from "react";
import DocumentLibrary from "@/components/dashboard/DocumentLibrary";
import Icon from "@/components/dashboard/Icon";

export default function DocumentsPage() {
  return (
    <>
      <div className="mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">
            Knowledge base
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-[2.1rem]">
            Documents
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            Explore documents indexed in your company knowledge workspace.
          </p>
        </div>
        <span className="inline-flex w-fit items-center gap-2 rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-xs font-medium text-slate-500">
          <Icon className="size-4 text-emerald-700" name="database" />
          Live document library
        </span>
      </div>

      <Suspense
        fallback={
          <div
            aria-label="Loading documents"
            className="h-80 animate-pulse rounded-2xl border border-slate-200 bg-white"
            role="status"
          >
            <span className="sr-only">Loading documents…</span>
          </div>
        }
      >
        <DocumentLibrary />
      </Suspense>
    </>
  );
}
