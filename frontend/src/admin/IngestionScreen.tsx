import { useCallback, useEffect, useState } from "react";
import {
  Database,
  AlertTriangle,
  Download,
  FileUp,
  Info,
  RefreshCw,
  Search,
  Upload,
  X,
} from "lucide-react";
import {
  AdminApiError,
  collectFilings,
  indexFiling,
  listCompanies,
  listDocuments,
  listIngestionEvents,
  previewFilings,
  reseedCorpus,
  RESEED_CONFIRMATION,
  startIndexing,
  uploadDocument,
  type EdgarFiling,
  type IngestionEvent,
  type KnownCompany,
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

      {/* Left column: the two ways you bring documents in yourself.
          Right column: EDGAR, and the note about the route it is not
          taking. Collect sits under Upload because the right column runs
          longer, and leaving it below the pair left this side blank.

          What arrived goes underneath both, where a seven-column table
          has the width it needs. */}
      {/* Two rows of two, not two columns of two. A column is its own
          flex context, so nothing lines up a row across them — the top
          cards ended sixteen pixels apart and the row below started at
          two different offsets. As grid rows they share a track and match
          by construction. */}
      <div className="screen__pair">
        <UploadPanel />
        <EdgarPanel />
      </div>

      <div className="screen__pair">
        <CollectPanel />
        <S3PipelinePanel />
      </div>

      <DocumentsPanel />

      {/* Repair and replace, side by side. One re-runs indexing over
          documents already stored; the other throws them away. Reading
          them together is the point — the cheap fix should be the one you
          reach for, and it is hard to prefer it if you never see it beside
          the expensive one. */}
      <div className="screen__pair">
        <ReindexPanel />
        <ReseedPanel />
      </div>

    </div>
  );
}

function UploadPanel() {
  const companies = useCompanies();
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
      <p className="screen__sublede">
        When you already have the file. Pick it and it is parsed and
        indexed.
      </p>

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
          <span className="screen__label">Company (optional)</span>
          <select
            className="screen__input"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
          >
            <option value="">No company</option>
            {companies.map((company) => (
              <option key={company.ticker} value={company.ticker}>
                {company.ticker} — {company.name}
              </option>
            ))}
          </select>
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
  const companies = useCompanies();
  const [ticker, setTicker] = useState("");
  const [forms, setForms] = useState<string[]>(["10-K", "10-Q"]);
  const [busy, setBusy] = useState(false);
  const [filings, setFilings] = useState<EdgarFiling[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    setBusy(true);
    setFilings(null);
    setError(null);

    try {
      const response = await previewFilings(ticker.trim(), forms.join(","), 10);

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
      <p className="screen__sublede">
        When you do not. Name a company and SEC says what it has filed;
        Index downloads and indexes the one you choose.
      </p>

      <form className="screen__card" onSubmit={submit}>
        <label className="screen__field">
          <span className="screen__label">Company</span>
          <select
            className="screen__input"
            value={ticker}
            onChange={(event) => setTicker(event.target.value)}
          >
            <option value="">Choose a company</option>
            {companies.map((company) => (
              <option key={company.ticker} value={company.ticker}>
                {company.ticker} — {company.name}
              </option>
            ))}
          </select>
          <span className="screen__hint">
            Resolved to the company's Central Index Key, which is what
            EDGAR is addressed by — there is no endpoint that takes a
            ticker.
          </span>
        </label>

        <fieldset className="screen__field screen__fieldset">
          <legend className="screen__label">Forms</legend>
          <div className="screen__checks">
            {FORM_TYPES.map(({ code, label }) => (
              <label key={code} className="screen__check">
                <input
                  type="checkbox"
                  checked={forms.includes(code)}
                  onChange={(event) =>
                    setForms((current) =>
                      event.target.checked
                        ? [...current, code]
                        : current.filter((f) => f !== code),
                    )
                  }
                />
                <span>
                  <strong>{code}</strong> {label}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

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
        <div className="screen__pane-head">
          <span className="screen__count">
            {filings.length} filing{filings.length === 1 ? "" : "s"}
          </span>
          <button
            type="button"
            className="screen__icon-btn"
            onClick={() => setFilings(null)}
            aria-label="Clear these results"
            title="Clear these results"
          >
            <X size={14} />
          </button>
        </div>
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

/**
 * The companies whose filings can be fetched.
 *
 * Loaded once and shared by every control that takes a ticker, so none of
 * them can offer a company the others do not. The server checks anyway —
 * a dropdown is a convenience, not a guarantee.
 */
function useCompanies(): KnownCompany[] {
  const [companies, setCompanies] = useState<KnownCompany[]>([]);

  useEffect(() => {
    let live = true;

    listCompanies()
      .then((loaded) => {
        if (live) setCompanies(loaded.companies);
      })
      .catch(() => undefined);

    return () => {
      live = false;
    };
  }, []);

  return companies;
}

// The API will not return more than this in one request, and a table of
// two hundred rows is already past the point of being read rather than
// searched.
const MAX_ROWS = 200;
const PAGE = 25;

function DocumentsPanel() {
  const [documents, setDocuments] = useState<StoredDocument[] | null>(null);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);

    try {
      const response = await listDocuments(limit);

      setDocuments(response.documents);
      setTotal(response.total);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not load the document list.",
      );
    } finally {
      setBusy(false);
    }
  }, [limit]);

  useEffect(() => {
    void load();
  }, [load]);

  /**
   * Reload, and collapse an expanded list back to one page.
   *
   * Refresh is for seeing what changed, and what changed is at the top.
   * Reloading two hundred rows to look at the first few is slower and
   * leaves the reader where they were rather than where they are looking.
   *
   * Setting the limit is enough to reload when the list is expanded --
   * load() depends on it -- but not when it is already 25, because the
   * value has not changed. Hence the branch.
   */
  function refresh() {
    if (limit !== PAGE) {
      setLimit(PAGE);
    } else {
      void load();
    }
  }

  const shown = documents?.length ?? 0;
  const more = total > shown;

  return (
    <section className="screen__pane">
      {/* Heading, count and Refresh on one line. The button used to sit in
          a row of its own between the heading and the table, which pushed
          them apart for no reason anyone could see. */}
      <div className="screen__pane-head">
        <h2 className="screen__name">Recent documents</h2>

        {documents && (
          <span className="screen__count">
            {shown} of {total}
          </span>
        )}

        <button
          type="button"
          className="screen__btn"
          onClick={() => refresh()}
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

      {more && (
        <div className="screen__more">
          <button
            type="button"
            className="screen__btn"
            onClick={() => setLimit((current) => Math.min(current + PAGE, MAX_ROWS))}
            disabled={busy || shown >= MAX_ROWS}
          >
            {shown >= MAX_ROWS
              ? `Showing the most recent ${MAX_ROWS}`
              : `Show ${Math.min(PAGE, total - shown)} more`}
          </button>
        </div>
      )}
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
      <p className="screen__sublede">
        Chunk and embed again, for documents already stored. The repair
        for one stuck in <code>processing</code>.
      </p>

      <form className="screen__card" onSubmit={submit}>
        {/* First in the card, matching the rebuild panel opposite,
            which opens with its warning. A caveat read before the control
            is a caveat; read after it, it is a footnote. */}
        <div className="screen__inline-note">
          <Info size={14} aria-hidden="true" />
          <div>
            <p className="screen__inline-note-title">
              This starts the work; it does not watch it.
            </p>
            <p className="screen__inline-note-body">
              Indexing runs as a background task with no job record, so a
              failure after this returns — a missing document, one that
              produces no chunks, or the embedding API being down — reaches
              the server log only. The document list is the check: refresh
              it and see whether the chunk count moved.
            </p>
          </div>
        </div>

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

/**
 * Index recent filings for several companies in one go.
 *
 * The single Index button in the lookup is for one filing you have looked
 * at. This is for filling the corpus: name the companies and walk away.
 * Additive and repeatable — a filing already held is skipped, so running
 * it twice costs nothing but the lookups.
 */
// Matches MAX_FILINGS_PER_RUN on the server. Shown here so the size of a
// run is visible before it is started, rather than arriving as a refusal.
const MAX_FILINGS_PER_RUN = 25;

// Matches SUPPORTED_FORMS on the server. Checkboxes rather than a text
// field: a mistyped form matches nothing at EDGAR, so the run reports
// success having fetched nothing at all.
const FORM_TYPES = [
  { code: "10-K", label: "Annual report" },
  { code: "10-Q", label: "Quarterly report" },
  { code: "8-K", label: "Material event" },
];

function CollectPanel() {
  const companies = useCompanies();
  const [tickers, setTickers] = useState<string[]>([]);
  const [forms, setForms] = useState<string[]>(["10-K"]);
  const [limit, setLimit] = useState("2");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    const wanted = tickers;

    if (wanted.length === 0) {
      setError("Choose at least one company.");
      return;
    }

    if (forms.length === 0) {
      setError("Choose at least one form.");
      return;
    }

    setBusy(true);
    setResult(null);
    setError(null);

    try {
      const accepted = await collectFilings(wanted, forms, Number(limit) || 1);

      setResult(accepted.message);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not start collection.",
      );
    } finally {
      setBusy(false);
    }
  }

  const planned = tickers.length * (Number(limit) || 0);
  const oversized = planned > MAX_FILINGS_PER_RUN;

  return (
    <section className="screen__pane">
      <h2 className="screen__name">Collect filings for several companies</h2>
      <p className="screen__sublede">
        Fetches and indexes recent filings without showing them to you
        first. Use the lookup above to choose one; use this to fill the
        corpus. A filing already held is skipped.
      </p>

      <form className="screen__card" onSubmit={submit}>
        <label className="screen__field">
          <span className="screen__label">Companies</span>
          <select
            className="screen__input screen__input--multi"
            multiple
            size={6}
            value={tickers}
            onChange={(event) =>
              setTickers(
                [...event.target.selectedOptions].map((option) => option.value),
              )
            }
          >
            {companies.map((company) => (
              <option key={company.ticker} value={company.ticker}>
                {company.ticker} — {company.name}
              </option>
            ))}
          </select>
          <span className="screen__hint">
            Hold Cmd or Ctrl to choose several. Only the fifty companies
            this corpus covers are listed — anything else has no financial
            metrics here to answer against.
          </span>
        </label>

        <fieldset className="screen__field screen__fieldset">
          <legend className="screen__label">Forms</legend>
          <div className="screen__checks">
            {FORM_TYPES.map(({ code, label }) => (
              <label key={code} className="screen__check">
                <input
                  type="checkbox"
                  checked={forms.includes(code)}
                  onChange={(event) =>
                    setForms((current) =>
                      event.target.checked
                        ? [...current, code]
                        : current.filter((f) => f !== code),
                    )
                  }
                />
                <span>
                  <strong>{code}</strong> {label}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="screen__field">
          <span className="screen__label">Filings per company</span>
          <input
            className="screen__input"
            type="number"
            min={1}
            max={MAX_FILINGS_PER_RUN}
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
          />
          <span className="screen__hint">
            Counted across all the forms, not per form — a company files
            three 10-Qs a year to one 10-K, so asking for 2 of both
            usually returns two quarterlies and no annual report.
            Companies × filings must come to {MAX_FILINGS_PER_RUN} or
            fewer, and one 10-K is around 1,500 chunks.
          </span>
        </label>

        {planned > 0 && (
          <p className={oversized ? "screen__error" : "screen__hint"}>
            {oversized
              ? `${planned} filings — more than the ${MAX_FILINGS_PER_RUN} allowed in one run. Choose fewer.`
              : `${planned} filing${planned === 1 ? "" : "s"}, roughly ${(
                  planned * 1500
                ).toLocaleString()} chunks.`}
          </p>
        )}

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

        <button
          type="submit"
          className="screen__submit"
          disabled={busy || oversized || planned === 0}
        >
          <Download size={15} />
          {busy ? "Starting…" : "Collect and index"}
        </button>
      </form>
    </section>
  );
}

/**
 * Rebuild the corpus from Alpha Vantage and Finnhub.
 *
 * Deliberately the least convenient thing on the screen. It empties four
 * tables and refetches live data that will not match what was there, so
 * the benchmark corpus and the ground truth built from it do not survive
 * it. The phrase has to be typed; there is no button that does this on
 * its own.
 */
function ReseedPanel() {
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const armed = confirm.trim() === RESEED_CONFIRMATION;

  async function submit(event: React.FormEvent) {
    event.preventDefault();

    setBusy(true);
    setResult(null);
    setError(null);

    try {
      const accepted = await reseedCorpus(confirm.trim());

      setResult(accepted.message);
      setConfirm("");
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not start the reseed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="screen__pane">
      <h2 className="screen__name">Rebuild the corpus from live sources</h2>
      <p className="screen__sublede">
        Empty the tables and fetch everything again from Alpha Vantage and
        Finnhub. Not reversible from here.
      </p>

      <form className="screen__card screen__card--danger" onSubmit={submit}>
        <div className="screen__warn">
          <AlertTriangle size={15} aria-hidden="true" />
          <div>
            <p className="screen__warn-title">This deletes the corpus.</p>
            <p className="screen__warn-body">
              Every document, chunk, company and financial metric is
              removed, then refetched from Alpha Vantage and Finnhub. The
              new data will not match the old — market caps move and news
              is replaced — so the benchmark baseline and the SQL ground
              truth derived from it no longer apply. Take a snapshot first
              if you want the current corpus back.
            </p>
          </div>
        </div>

        <label className="screen__field">
          <span className="screen__label">
            Type <code>{RESEED_CONFIRMATION}</code> to confirm
          </span>
          <input
            className="screen__input"
            type="text"
            value={confirm}
            placeholder={RESEED_CONFIRMATION}
            onChange={(event) => setConfirm(event.target.value)}
          />
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

        <button
          type="submit"
          className="screen__submit screen__submit--danger"
          disabled={busy || !armed}
        >
          <AlertTriangle size={15} />
          {busy ? "Starting…" : "Delete and rebuild"}
        </button>
      </form>
    </section>
  );
}

/**
 * The bucket route: what it is, and what has come through it.
 *
 * A panel rather than a loose note, so it sits level with Collect
 * opposite: both are about filling the corpus without watching each
 * filing, and the difference is only whether a queue and a bucket are
 * doing it.
 *
 * Nothing to press. It describes what runs elsewhere, and saying which
 * configuration is missing is the useful part.
 */
function S3PipelinePanel() {
  const [events, setEvents] = useState<IngestionEvent[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);

    try {
      const response = await listIngestionEvents(25, "s3");

      setEvents(response.events);
    } catch (caught) {
      setError(
        caught instanceof AdminApiError
          ? caught.message
          : "Could not load the processing history.",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="screen__pane screen__pane--fill">
      <div className="screen__pane-head">
        <h2 className="screen__name">S3 pipeline</h2>
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
      <p className="screen__sublede">
        Filings written to the raw S3 bucket, where the notification puts
        each on an SQS queue for the ingestion worker — which keeps the
        original file. Configured with RAW_BUCKET and INGESTION_QUEUE_URL.
      </p>

      {error && (
        <p className="screen__error" role="alert">
          {error}
        </p>
      )}

      {events && (
        <div className="screen__table-wrap">
          <table className="screen__table">
            <thead>
              <tr>
                <th>File</th>
                <th>Processed</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                // Stored or not. The specific reason still reads under the
                // name; the column answers the only question asked of it.
                const stored = event.outcome === "indexed";

                return (
                  <tr key={event.id}>
                    <td>
                      {event.reference}
                      {event.detail && (
                        <span className="screen__slug">{event.detail}</span>
                      )}
                      {stored && event.chunks != null && (
                        <span className="screen__slug">
                          {event.chunks.toLocaleString()} chunks
                        </span>
                      )}
                    </td>
                    <td>
                      <span className="screen__slug">
                        {event.at
                          ? event.at.replace("T", " ").slice(0, 19)
                          : "—"}
                      </span>
                    </td>
                    <td>
                      <span
                        className={
                          stored
                            ? "screen__pill screen__pill--ok"
                            : "screen__pill screen__pill--bad"
                        }
                      >
                        {stored ? "success" : "failed"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

