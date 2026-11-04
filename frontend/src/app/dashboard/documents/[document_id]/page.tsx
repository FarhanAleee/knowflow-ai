import { Suspense } from "react";
import DocumentDetails from "@/components/dashboard/DocumentDetails";

async function DocumentDetailsContent({
  params,
}: {
  params: Promise<{ document_id: string }>;
}) {
  const { document_id: documentId } = await params;
  return <DocumentDetails documentId={documentId} />;
}

export default function DocumentDetailsPage({
  params,
}: {
  params: Promise<{ document_id: string }>;
}) {
  return (
    <Suspense
      fallback={
        <div
          aria-label="Loading document details"
          className="h-72 animate-pulse rounded-2xl border border-slate-200 bg-white"
          role="status"
        >
          <span className="sr-only">Loading document details…</span>
        </div>
      }
    >
      <DocumentDetailsContent params={params} />
    </Suspense>
  );
}
