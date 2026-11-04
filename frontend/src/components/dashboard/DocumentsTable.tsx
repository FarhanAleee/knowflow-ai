import Link from "next/link";
import type { ManagedDocument } from "@/lib/api";
import { formatFileSize } from "@/lib/api";
import Icon from "@/components/dashboard/Icon";

function StatusBadge({ status }: { status: string }) {
  const indexed = status.toLowerCase() === "indexed";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${
        indexed
          ? "bg-emerald-50 text-emerald-800"
          : "bg-amber-50 text-amber-800"
      }`}
    >
      <span
        className={`size-1.5 rounded-full ${
          indexed ? "bg-emerald-500" : "bg-amber-500"
        }`}
      />
      {status}
    </span>
  );
}

function DocumentLink({ document }: { document: ManagedDocument }) {
  return (
    <Link
      aria-label={`View details for ${document.filename}`}
      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm font-semibold text-emerald-800 transition-colors hover:bg-emerald-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"
      href={`/dashboard/documents/${encodeURIComponent(document.document_id)}`}
    >
      Details
      <Icon className="size-4" name="arrow" />
    </Link>
  );
}

export default function DocumentsTable({
  documents,
}: {
  documents: ManagedDocument[];
}) {
  return (
    <>
      <div className="hidden overflow-hidden rounded-2xl border border-slate-200 bg-white md:block">
        <table className="w-full border-collapse text-left">
          <thead className="bg-slate-50/80">
            <tr className="border-b border-slate-200">
              <th className="px-6 py-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Document
              </th>
              <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Status
              </th>
              <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Chunks
              </th>
              <th className="px-4 py-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
                File size
              </th>
              <th className="px-5 py-4 text-right text-xs font-semibold uppercase tracking-wide text-slate-500">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {documents.map((document) => (
              <tr
                className="transition-colors hover:bg-slate-50/70"
                key={document.document_id}
              >
                <td className="max-w-[360px] px-6 py-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                      <Icon className="size-[18px]" name="file" />
                    </span>
                    <span className="min-w-0">
                      <span
                        className="block truncate text-sm font-semibold text-slate-800"
                        title={document.filename}
                      >
                        {document.filename}
                      </span>
                      <span className="mt-1 block text-xs uppercase text-slate-400">
                        {document.file_type}
                      </span>
                    </span>
                  </div>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge status={document.indexing_status} />
                </td>
                <td className="px-4 py-4 text-sm tabular-nums text-slate-600">
                  {document.chunks_indexed.toLocaleString()}
                </td>
                <td className="px-4 py-4 text-sm text-slate-600">
                  {formatFileSize(document.file_size)}
                </td>
                <td className="px-5 py-4 text-right">
                  <DocumentLink document={document} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ul className="space-y-3 md:hidden">
        {documents.map((document) => (
          <li
            className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm shadow-slate-950/[0.02]"
            key={document.document_id}
          >
            <div className="flex items-start gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
                <Icon className="size-[18px]" name="file" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="break-words text-sm font-semibold text-slate-800">
                  {document.filename}
                </p>
                <p className="mt-1 text-xs uppercase text-slate-400">
                  {document.file_type}
                </p>
              </div>
              <StatusBadge status={document.indexing_status} />
            </div>
            <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
              <p className="text-xs text-slate-500">
                {document.chunks_indexed.toLocaleString()} chunks
                <span className="mx-2 text-slate-300">·</span>
                {formatFileSize(document.file_size)}
              </p>
              <DocumentLink document={document} />
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
