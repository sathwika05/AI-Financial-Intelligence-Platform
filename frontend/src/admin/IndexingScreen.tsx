import { useState } from "react";
import { Database, Info } from "lucide-react";
import { AdminApiError, startIndexing } from "./api";
import "./AdminScreens.css";

/**
 * Trigger chunk -> embed -> store.
 *
 * There is no upload here, because there is no upload anywhere: documents
 * arrive through the ingestion pipeline from Alpha Vantage, and this
 * indexes what is already in the documents table.
 *
 * There is no job list either. The endpoint queues a background task and
 * returns; no job row is written, no progress is reported, and a failure
 * after the queue reaches the server log and nothing else. Saying so is
 * better than a spinner that resolves to a lie.
 */
export function IndexingScreen() {
  const [documentId, setDocumentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    setBusy(true);
    setResult(null);
    setError(null);

    const trimmed = documentId.trim();

    try {
      const response = await startIndexing(
        trimmed ? { document_id: Number(trimmed) } : {},
      );

      setResult(response.message);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not start indexing.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="screen">
      <header className="screen__head">
        <h1 className="screen__title">Indexing</h1>
        <p className="screen__lede">
          Split a document into chunks, embed each one, and store the vectors
          for retrieval. Documents come from the ingestion pipeline; this
          indexes what is already stored.
        </p>
      </header>

      <form className="screen__card" onSubmit={submit}>
        <label className="screen__field">
          <span className="screen__label">Document ID</span>
          <input
            className="screen__input"
            type="number"
            min={1}
            inputMode="numeric"
            placeholder="Leave empty to index everything unindexed"
            value={documentId}
            onChange={(event) => setDocumentId(event.target.value)}
          />
          <span className="screen__hint">
            One document, or the whole backlog if left empty.
          </span>
        </label>

        {error && (
          <p className="screen__error" role="alert">
            {error}
          </p>
        )}

        {result && (
          <p className="screen__ok" role="status">
            {result}
          </p>
        )}

        <button type="submit" className="screen__submit" disabled={busy}>
          <Database size={15} />
          {busy ? "Starting…" : "Start indexing"}
        </button>
      </form>

      <aside className="screen__aside">
        <Info size={15} className="screen__aside-icon" aria-hidden="true" />
        <div>
          <p className="screen__aside-title">
            This starts the work; it does not watch it.
          </p>
          <p className="screen__aside-body">
            Indexing runs as a background task with no job record, so there
            is no progress to show and no way to report a failure that
            happens after this returns — a missing document, a document
            that produces no chunks, or the embedding API being down all
            reach the server log only. Check the API logs to confirm a run
            finished.
          </p>
        </div>
      </aside>
    </div>
  );
}
