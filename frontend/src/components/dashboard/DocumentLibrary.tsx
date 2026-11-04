"use client";

import { useCallback, useEffect, useState } from "react";
import DocumentsTable from "@/components/dashboard/DocumentsTable";
import Icon from "@/components/dashboard/Icon";
import { getDocuments, type DocumentListResponse } from "@/lib/api";

const PAGE_SIZE = 20;

function DocumentSkeleton() {
  return (
    <div
      aria-label="Loading documents"
      className="space-y-3"
      role="status"
    >
      <span className="sr-only">Loading documents…</span>
      {[0, 1, 2, 3].map((item) => (
        <div
          className="h-[76px] animate-pulse rounded-2xl border border-slate-200 bg-white"
          key={item}
        />
      ))}
    </div>
  );
}

export default function DocumentLibrary() {
  const [offset, setOffset] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<DocumentListResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();

    getDocuments({ offset, limit: PAGE_SIZE, signal: controller.signal })
      .then(setResult)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "Unable to load documents. Please try again.",
        );
        setResult(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [offset, attempt]);

  const retry = useCallback(() => {
    setLoading(true);
    setErrorMessage(null);
    setAttempt((value) => value + 1);
  }, []);
  const changePage = (nextOffset: number) => {
    setLoading(true);
    setErrorMessage(null);
    setOffset(nextOffset);
  };
  const total = result?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + (result?.documents.length ?? 0), total);

  return (
    <section aria-label="Document library">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-slate-900">
            All documents
          </h2>
          {!loading && !errorMessage && (
            <p className="mt-1 text-sm text-slate-500">
              {total.toLocaleString()} indexed{" "}
              {total === 1 ? "document" : "documents"}
            </p>
          )}
        </div>
        {result && result.total > PAGE_SIZE && (
          <p className="text-xs text-slate-500">
            Showing {pageStart}–{pageEnd} of {total}
          </p>
        )}
      </div>

      {loading ? (
        <DocumentSkeleton />
      ) : errorMessage ? (
        <div
          aria-live="polite"
          className="rounded-2xl border border-rose-200 bg-white px-6 py-10 text-center"
          role="alert"
        >
          <p className="font-semibold text-slate-800">
            We couldn&apos;t load your documents
          </p>
          <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
            {errorMessage}
          </p>
          <button
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
            onClick={retry}
            type="button"
          >
            <Icon className="size-4" name="refresh" />
            Try again
          </button>
        </div>
      ) : result && result.total === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
          <span className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700">
            <Icon className="size-6" name="files" />
          </span>
          <h3 className="mt-4 font-semibold text-slate-900">
            Your library is ready
          </h3>
          <p className="mx-auto mt-2 max-w-sm text-sm leading-6 text-slate-500">
            No indexed documents were returned by the document service.
          </p>
        </div>
      ) : result && result.documents.length > 0 ? (
        <>
          <DocumentsTable documents={result.documents} />
          {result.total > PAGE_SIZE && (
            <div className="mt-5 flex items-center justify-between">
              <p className="text-xs text-slate-500">
                Page {Math.floor(offset / PAGE_SIZE) + 1} of{" "}
                {Math.ceil(result.total / PAGE_SIZE)}
              </p>
              <div className="flex gap-2">
                <button
                  aria-label="Previous page"
                  className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
                  disabled={offset === 0}
                  onClick={() => changePage(Math.max(0, offset - PAGE_SIZE))}
                  type="button"
                >
                  Previous
                </button>
                <button
                  aria-label="Next page"
                  className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
                  disabled={offset + result.documents.length >= result.total}
                  onClick={() => changePage(offset + PAGE_SIZE)}
                  type="button"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
