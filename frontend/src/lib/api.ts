export interface ManagedDocument {
  document_id: string;
  filename: string;
  file_type: string;
  file_size: number | null;
  chunks_indexed: number;
  indexing_status: string;
}

export interface DocumentListResponse {
  documents: ManagedDocument[];
  total: number;
  offset: number;
  limit: number;
}

export interface DocumentListOptions {
  offset?: number;
  limit?: number;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(
      "Unable to connect to the document service. Check that the backend is running, then try again.",
      0,
    );
  }

  if (!response.ok) {
    const message =
      response.status === 404
        ? "This document could not be found."
        : response.status >= 500
          ? "The document service is temporarily unavailable. Please try again."
          : "The document request could not be completed. Please try again.";
    throw new ApiError(message, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(
      "The document service returned an unexpected response. Please try again.",
      response.status,
    );
  }
}

export function getDocuments({
  offset = 0,
  limit = 20,
  signal,
}: DocumentListOptions = {}): Promise<DocumentListResponse> {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  return requestJson<DocumentListResponse>(
    `/api/documents?${query.toString()}`,
    signal,
  );
}

export function getDocument(
  documentId: string,
  signal?: AbortSignal,
): Promise<ManagedDocument> {
  return requestJson<ManagedDocument>(
    `/api/documents/${encodeURIComponent(documentId)}`,
    signal,
  );
}

export async function getAllDocuments(
  signal?: AbortSignal,
): Promise<DocumentListResponse> {
  const pageSize = 100;
  const firstPage = await getDocuments({ offset: 0, limit: pageSize, signal });
  const documents = [...firstPage.documents];

  for (let offset = firstPage.limit; offset < firstPage.total; offset += pageSize) {
    const page = await getDocuments({ offset, limit: pageSize, signal });
    documents.push(...page.documents);
    if (page.documents.length === 0) {
      break;
    }
  }

  return { ...firstPage, documents };
}

export function formatFileSize(fileSize: number | null): string {
  if (fileSize === null || !Number.isFinite(fileSize) || fileSize < 0) {
    return "Not available";
  }
  if (fileSize < 1024) {
    return `${fileSize} B`;
  }
  if (fileSize < 1024 * 1024) {
    return `${(fileSize / 1024).toFixed(1)} KB`;
  }
  return `${(fileSize / (1024 * 1024)).toFixed(1)} MB`;
}
