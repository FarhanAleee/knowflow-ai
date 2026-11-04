"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Icon from "@/components/dashboard/Icon";
import { formatFileSize, getDocument, type ManagedDocument } from "@/lib/api";

export default function DocumentDetails({
  documentId,
}: {
  documentId: string;
}) {
  const [state, setState] = useState<
    | { documentId: string; status: "loading" }
    | { documentId: string; status: "error"; message: string }
    | { documentId: string; status: "success"; document: ManagedDocument }
  >({ documentId, status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getDocument(documentId, controller.signal)
      .then((document) => {
        setState({ documentId, status: "success", document });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setState({
          documentId,
          status: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to load document details. Please try again.",
        });
      });

    return () => controller.abort();
  }, [documentId, attempt]);

  const currentState =
    state.documentId === documentId
      ? state
      : { documentId, status: "loading" as const };
  const document =
    currentState.status === "success" ? currentState.document : null;

  return (
    <>
      <Link
        className="mb-7 inline-flex items-center gap-2 rounded-lg text-sm font-semibold text-emerald-800 transition-colors hover:text-emerald-950 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
        href="/dashboard/documents"
      >
        <Icon className="size-4 rotate-180" name="arrow" />
        Back to documents
      </Link>
      <div className="mb-7">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-700">
          Document details
        </p>
        <h1 className="mt-2 break-words text-3xl font-semibold tracking-[-0.04em] text-slate-950">
          {document?.filename ?? "Document"}
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          Metadata returned by your document service.
        </p>
      </div>

      {currentState.status === "loading" ? (
        <div
          aria-label="Loading document details"
          className="h-72 animate-pulse rounded-2xl border border-slate-200 bg-white"
          role="status"
        >
          <span className="sr-only">Loading document details…</span>
        </div>
      ) : currentState.status === "error" ? (
        <div
          aria-live="polite"
          className="rounded-2xl border border-rose-200 bg-white px-6 py-10 text-center"
          role="alert"
        >
          <p className="font-semibold text-slate-800">
            We couldn&apos;t load this document
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            {currentState.message}
          </p>
          <button
            className="mt-5 inline-flex items-center gap-2 rounded-xl bg-emerald-800 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
            onClick={() => {
              setState({ documentId, status: "loading" });
              setAttempt((value) => value + 1);
            }}
            type="button"
          >
            <Icon className="size-4" name="refresh" />
            Try again
          </button>
        </div>
      ) : document ? (
        <section
          aria-label="Document metadata"
          className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm shadow-slate-950/[0.02]"
        >
          <div className="flex flex-col gap-5 border-b border-slate-100 bg-gradient-to-br from-emerald-50/80 to-white p-6 sm:flex-row sm:items-center sm:p-8">
            <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-white text-emerald-700 shadow-sm">
              <Icon className="size-7" name="file" />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="break-all text-lg font-semibold text-slate-900">
                  {document.filename}
                </h2>
                <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold capitalize text-emerald-800">
                  {document.indexing_status}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-500">
                {document.file_type.toUpperCase()} document
              </p>
            </div>
          </div>

          <dl className="grid gap-x-8 divide-y divide-slate-100 px-6 sm:grid-cols-2 sm:divide-y-0 sm:p-8">
            <div className="border-b border-slate-100 py-5 sm:border-b-0 sm:py-3">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                File size
              </dt>
              <dd className="mt-2 text-sm font-medium text-slate-800">
                {formatFileSize(document.file_size)}
              </dd>
            </div>
            <div className="border-b border-slate-100 py-5 sm:border-b-0 sm:py-3">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Indexed chunks
              </dt>
              <dd className="mt-2 text-sm font-medium tabular-nums text-slate-800">
                {document.chunks_indexed.toLocaleString()}
              </dd>
            </div>
            <div className="border-b border-slate-100 py-5 sm:py-3">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Indexing status
              </dt>
              <dd className="mt-2 text-sm font-medium capitalize text-slate-800">
                {document.indexing_status}
              </dd>
            </div>
            <div className="py-5 sm:py-3">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Upload date
              </dt>
              <dd className="mt-2 text-sm font-medium text-slate-500">
                Not provided by the document service
              </dd>
            </div>
            <div className="border-t border-slate-100 py-5 sm:col-span-2 sm:pt-6">
              <dt className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                Document ID
              </dt>
              <dd className="mt-2 break-all rounded-xl bg-slate-50 px-3.5 py-3 font-mono text-xs leading-5 text-slate-600">
                {document.document_id}
              </dd>
            </div>
          </dl>
        </section>
      ) : null}
    </>
  );
}
