"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import DocumentsTable from "@/components/dashboard/DocumentsTable";
import Icon from "@/components/dashboard/Icon";
import {
  formatFileSize,
  getAllDocuments,
  type DocumentListResponse,
} from "@/lib/api";

function OverviewSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading workspace overview">
      <span className="sr-only">Loading workspace overview…</span>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div
            className="h-32 animate-pulse rounded-2xl border border-slate-200 bg-white"
            key={item}
          />
        ))}
      </div>
      <div className="h-64 animate-pulse rounded-2xl border border-slate-200 bg-white" />
    </div>
  );
}

export default function DashboardOverview() {
  const [result, setResult] = useState<DocumentListResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getAllDocuments(controller.signal)
      .then(setResult)
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "Unable to load workspace metrics. Please try again.",
        );
        setResult(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [attempt]);

  const documents = result?.documents ?? [];
  const totalChunks = documents.reduce(
    (total, document) => total + document.chunks_indexed,
    0,
  );
  const formatCount = new Set(
    documents.map((document) => document.file_type.toLowerCase()),
  ).size;
  const knownFileSizes = documents.flatMap((document) =>
    document.file_size === null ? [] : [document.file_size],
  );
  const totalSize =
    knownFileSizes.length === 0
      ? null
      : knownFileSizes.reduce((total, fileSize) => total + fileSize, 0);
  const metrics = [
    {
      label: "Indexed documents",
      value: result ? result.total.toLocaleString() : "—",
      detail: "Available in your library",
      icon: "files" as const,
      iconStyle: "bg-emerald-50 text-emerald-700",
    },
    {
      label: "Searchable chunks",
      value: result ? totalChunks.toLocaleString() : "—",
      detail: "Across indexed documents",
      icon: "layers" as const,
      iconStyle: "bg-blue-50 text-blue-700",
    },
    {
      label: "Document formats",
      value: result ? formatCount.toLocaleString() : "—",
      detail: "Represented in your library",
      icon: "file" as const,
      iconStyle: "bg-violet-50 text-violet-700",
    },
    {
      label: "Known file size",
      value: result ? formatFileSize(totalSize) : "—",
      detail: "Sum of available file sizes",
      icon: "database" as const,
      iconStyle: "bg-amber-50 text-amber-700",
    },
  ];

  return (
    <>
      <div className="mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">
            Your workspace
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-[2.1rem]">
            Overview
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
            A clear view of the knowledge your team has indexed and made
            searchable.
          </p>
        </div>
        <Link
          className="inline-flex w-fit items-center gap-2 rounded-xl bg-emerald-800 px-4 py-2.5 text-sm font-semibold text-white shadow-sm shadow-emerald-950/10 transition-all hover:-translate-y-0.5 hover:bg-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
          href="/dashboard/documents"
        >
          Browse documents
          <Icon className="size-4" name="arrow" />
        </Link>
      </div>

      {loading ? (
        <OverviewSkeleton />
      ) : errorMessage ? (
        <div
          aria-live="polite"
          className="rounded-2xl border border-rose-200 bg-white px-6 py-10 text-center"
          role="alert"
        >
          <p className="font-semibold text-slate-800">
            Workspace data is unavailable
          </p>
          <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-slate-500">
            {errorMessage}
          </p>
          <button
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
            onClick={() => {
              setLoading(true);
              setErrorMessage(null);
              setAttempt((value) => value + 1);
            }}
            type="button"
          >
            <Icon className="size-4" name="refresh" />
            Retry connection
          </button>
        </div>
      ) : (
        <>
          <section
            aria-label="Document library metrics"
            className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
          >
            {metrics.map((metric) => (
              <article
                className="rounded-2xl border border-slate-200/90 bg-white p-5 shadow-sm shadow-slate-950/[0.02] transition-all hover:-translate-y-0.5 hover:shadow-md hover:shadow-slate-950/[0.04]"
                key={metric.label}
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-slate-500">
                    {metric.label}
                  </p>
                  <span
                    className={`flex size-9 items-center justify-center rounded-xl ${metric.iconStyle}`}
                  >
                    <Icon className="size-[18px]" name={metric.icon} />
                  </span>
                </div>
                <p className="mt-5 text-[1.7rem] font-semibold tracking-tight text-slate-900">
                  {metric.value}
                </p>
                <p className="mt-1 text-xs text-slate-400">{metric.detail}</p>
              </article>
            ))}
          </section>

          <section className="mt-8">
            <div className="mb-5 flex items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-700">
                  Library
                </p>
                <h2 className="mt-1.5 text-lg font-semibold tracking-tight text-slate-900">
                  Available documents
                </h2>
              </div>
              {documents.length > 5 && (
                <Link
                  className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-800 transition-colors hover:text-emerald-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
                  href="/dashboard/documents"
                >
                  View all
                  <Icon className="size-4" name="chevron" />
                </Link>
              )}
            </div>
            {documents.length > 0 ? (
              <DocumentsTable documents={documents.slice(0, 5)} />
            ) : (
              <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
                <span className="mx-auto flex size-11 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700">
                  <Icon className="size-5" name="files" />
                </span>
                <h3 className="mt-4 text-sm font-semibold text-slate-900">
                  No indexed documents
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  The document service did not return any indexed documents.
                </p>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
