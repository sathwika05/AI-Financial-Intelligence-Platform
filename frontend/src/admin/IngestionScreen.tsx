import { useCallback, useEffect, useState } from "react";
import {
  Database,
  Download,
  FileUp,
  Info,
  RefreshCw,
  Search,
  Upload,
} from "lucide-react";
import {
  AdminApiError,
  indexFiling,
  listDocuments,
  previewFilings,
  startIndexing,
  uploadDocument,
  type EdgarFiling,
  type StoredDocument,
} from "./api";
import "./AdminScreens.css";

/**
 * Getting documents into the corpus, and seeing what arrived.
 *
 * Three panels, in the order you would use them.
 *
 * EDGAR preview reads a company's filing index and downloads nothing. It
 * needs only SEC_USER_AGENT, so it is the one part of the EDGAR path that
 * can be checked without a bucket — and it is the part most likely to be
 * wrong, because the shape of what SEC returns is SEC's to decide.
 *
 * Upload parses a file through the same code the queue worker uses and
 * indexes it directly, with no S3 in the path. On a laptop that is the
 * only way to run a document end to end; on a real deployment it is still
 * the honest way to find out whether a particular file can be read,
 * because it fails in the response rather than in a log on another
 * machine.
 *
 * The document list exists because "did that work?" was previously only
 * answerable by reading the server log. Chunk count is shown next to
 * status deliberately: a document can be ready and useless if it produced
 * nothing.
 */
export function IngestionScreen() {
  return (
    <div className="screen screen--wide">
      <header className="screen__head">
        <h1 className="screen__title">Ingestion</h1>
        <p className="screen__lede">
          Bring filings into the corpus, and see what is in it. Uploading
          parses and indexes a file directly; collection through S3 (Amazon's
          Simple Storage Service) runs on the deployment that has a bucket.
        </p>
      </header>

      {/* The two ways a document gets in, side by side: they are
          alternatives, not steps, and stacking them read as an order to
          follow. What arrived goes underneath, where a seven-column
          table has the width it needs. */}
      <div className="screen__pair">
        <UploadPanel />
        <EdgarPanel />
      </div>

      <aside className="screen__aside">
        <Info size={15} className="screen__aside-icon" aria-hidden="true" />
        <div>
          <p className="screen__aside-title">
            Index downloads the filing and indexes it here, with no bucket
            involved.
          </p>
          <p className="screen__aside-body">
            The scheduled collector takes the other route: it writes each
            filing to the S3 raw bucket, and the bucket notification hands
            it to the ingestion worker. That path needs RAW_BUCKET and
            INGESTION_QUEUE_URL and leaves the raw document in object
            storage. Either way the filing becomes the same row, so
            indexing one here does not stop the collector recognising it
            later.
          </p>
        </div>
      </aside>

      <DocumentsPanel />
      <ReindexPanel />
    </div>
  );
}

function UploadPanel() {
  const [file, setFile] = useState<File | null>(null);
  const [ticker, setTicker] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    if (!file) {
      setError("Choose a PDF or HTML filing first.");
      return;
    }

    setBusy(true);
    setResult(null);
    setError(null);

    try {
      const accepted = await uploadDocument(file, ticker);

      setResult(
        `Stored as document ${accepted.document_id} — ` +
          `${accepted.characters.toLocaleString()} characters extracted. ` +
          `${accepted.message}`,
      );
      setFile(null);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not upload that file.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen__pane">
      <h2 className="screen__name">Upload a filing</h2>

      <form className="screen__card" onSubmit={submit}>
        <label className="screen__field">
          <span className="screen__label">File</span>
          <input
            className="screen__input"
            type="file"
            accept=".pdf,.htm,.html"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setResult(null);
              setError(null);
            }}
          />
          <span className="screen__hint">
            PDF or HTML. A scanned PDF is read by optical character
            recognition (OCR), which takes a few seconds a page.
          </span>
        </label>

        <label className="screen__field">
          <span className="screen__label">Ticker (optional)</span>
          <input
            className="screen__input"
            type="text"
            placeholder="AAPL"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
          />
          <span className="screen__hint">
            Links the document to a company so it can be filtered by one.
            Without it the document is still indexed and still retrievable.
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
          <Upload size={15} />
          {busy ? "Parsing…" : "Upload and index"}
        </button>
      </form>
    </section>
  );
}

function EdgarPanel() {
  const [ticker, setTicker] = useState("");
  const [forms, setForms] = useState("10-K,10-Q");
  const [busy, setBusy] = useState(false);
  const [filings, setFilings] = useState<EdgarFiling[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    setBusy(true);
    setFilings(null);
    setError(null);

    try {
      const response = await previewFilings(ticker.trim(), forms, 10);

      setFilings(response.filings);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not reach EDGAR.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen__pane">
      <h2 className="screen__name">Look up SEC EDGAR filings</h2>

      <form className="screen__card" onSubmit={submit}>
        <label className="screen__field">
          <span className="screen__label">Ticker</span>
          <input
            className="screen__input"
            type="text"
            placeholder="AAPL"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
          />
          <span className="screen__hint">
            Resolved to the company's Central Index Key, which is what
            EDGAR is addressed by — there is no endpoint that takes a
            ticker.
          </span>
        </label>

        <label className="screen__field">
          <span className="screen__label">Forms</span>
          <input
            className="screen__input"
            type="text"
            value={forms}
            onChange={(event) => setForms(event.target.value)}
          />
          <span className="screen__hint">
            Comma separated. A 10-K is the annual report, a 10-Q the
            quarterly one; an 8-K discloses a single material event.
          </span>
        </label>

        {error && (
          <p className="screen__error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="screen__submit" disabled={busy}>
          <Search size={15} />
          {busy ? "Asking EDGAR…" : "List filings"}
        </button>
      </form>

      {filings && filings.length === 0 && (
        <p className="screen__note">
          EDGAR lists no filings of those forms for that company.
        </p>
      )}

      {filings && filings.length > 0 && (
        <div className="screen__table-wrap">
          <table className="screen__table">
            <thead>
              <tr>
                <th>Form</th>
                <th>Filed</th>
                <th>Document</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filings.map((filing) => (
                <tr key={filing.accession}>
                  <td>{filing.form}</td>
                  <td>{filing.filing_date}</td>
                  <td>
                    <a
                      href={filing.url}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {filing.document}
                    </a>
                    <span className="screen__slug"> {filing.accession}</span>
                  </td>
                  <td className="screen__col-actions">
                    <IndexButton filing={filing} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

    </section>
  );
}

function DocumentsPanel() {
  const [documents, setDocuments] = useState<StoredDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);

    try {
      const response = await listDocuments(25);

      setDocuments(response.documents);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not load the document list.",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="screen__pane">
      <h2 className="screen__name">Recent documents</h2>

      <div className="screen__col-actions">
        <button
          type="button"
          className="screen__btn"
          onClick={() => void load()}
          disabled={busy}
        >
          <RefreshCw size={14} />
          {busy ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <p className="screen__error" role="alert">
          {error}
        </p>
      )}

      {documents && documents.length === 0 && (
        <p className="screen__note">
          <FileUp size={14} aria-hidden="true" /> Nothing in the corpus yet.
        </p>
      )}

      {documents && documents.length > 0 && (
        <div className="screen__table-wrap">
          <table className="screen__table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Type</th>
                <th>Source</th>
                <th>Ticker</th>
                <th>Chunks</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id}>
                  <td>
                    <span className="screen__slug">{document.id}</span>
                  </td>
                  <td>{document.title ?? "—"}</td>
                  <td>{document.doc_type ?? "—"}</td>
                  <td>{document.source ?? "—"}</td>
                  <td>{document.ticker ?? "—"}</td>
                  <td>{document.chunks}</td>
                  <td>
                    <span
                      className={
                        document.status === "ready"
                          ? "screen__pill screen__pill--ok"
                          : "screen__pill screen__pill--warn"
                      }
                    >
                      {document.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="screen__footnote">
        A document is <code>processing</code> from the moment its row is
        written until indexing returns. One that stays there did not
        finish, and its chunk count says how far it got.
      </p>
    </section>
  );
}

/**
 * Re-run chunk -> embed -> store over documents already in the table.
 *
 * Separate from upload because it indexes what is stored rather than
 * bringing anything in — the case it exists for is a document whose
 * indexing failed, which the list above now makes findable.
 */
function ReindexPanel() {
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
    <section className="screen__pane">
      <h2 className="screen__name">Re-index stored documents</h2>

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
            Indexing runs as a background task with no job record, so a
            failure after this returns — a missing document, one that
            produces no chunks, or the embedding API being down — reaches
            the server log only. The list above is the check: refresh it
            and see whether the chunk count moved.
          </p>
        </div>
      </aside>
    </section>
  );
}

/**
 * Download one filing and index it.
 *
 * The identifiers go up, never the URL — the server rebuilds it and
 * checks the host, so this cannot be pointed anywhere else.
 *
 * A 409 means the corpus already holds this filing. That is the answer,
 * not an error, so it reads as one.
 */
function IndexButton({ filing }: { filing: EdgarFiling }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);

    try {
      const accepted = await indexFiling({
        cik: filing.cik,
        accession: filing.accession,
        form: filing.form,
        filing_date: filing.filing_date,
        primary_document: filing.document,
        ticker: filing.ticker,
      });

      setDone(`Document ${accepted.document_id}`);
    } catch (caught) {
      const message =
        caught instanceof AdminApiError
          ? caught.message
          : "Could not index that filing.";

      if (caught instanceof AdminApiError && caught.status === 409) {
        setDone("Already indexed");
      } else {
        setError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return <span className="screen__pill screen__pill--ok">{done}</span>;
  }

  return (
    <>
      <button
        type="button"
        className="screen__btn"
        onClick={() => void submit()}
        disabled={busy}
      >
        <Download size={13} />
        {busy ? "Indexing…" : "Index"}
      </button>
      {error && (
        <span className="screen__error" role="alert">
          {error}
        </span>
      )}
    </>
  );
}
