import { useRef, useState } from "react";
import { getErrorMessage, previewCsv, uploadCsv } from "../services/api";
import Icon from "./Icons";

const MAX_MB = 50; // keep in sync with MAX_UPLOAD_MB in backend/app/main.py

const ROLE_FIELDS = [
  { key: "product_name", label: "Item / record name", hint: "What each row is (optional)" },
  { key: "category", label: "Category / group", hint: "Used for the category chart (optional)" },
  { key: "rating", label: "Rating", hint: "0-5, 0-10 or 0-100 scale" },
  { key: "price", label: "Price / amount", hint: "Numeric" },
  { key: "discount", label: "Discount", hint: "A % value or Yes/No" },
];

const MODES = [
  { value: "auto", label: "Auto (recommended)" },
  { value: "rules", label: "Rule-based: rating, discount, price" },
  { value: "anomaly", label: "Statistical: outliers in any numeric columns" },
];

const MODE_NAMES = { rules: "Rule-based", anomaly: "Statistical outliers" };

export default function Upload({ onUploaded, onViewDashboard }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [mapping, setMapping] = useState({});
  const [mode, setMode] = useState("auto");

  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const runPreview = async (f) => {
    setPreviewing(true);
    try {
      const p = await previewCsv(f);
      setPreview(p);
      setMapping({ ...p.detected });
      setMode("auto");
    } catch (err) {
      setPreview(null);
      setError(getErrorMessage(err));
    } finally {
      setPreviewing(false);
    }
  };

  const pickFile = (f) => {
    setResult(null);
    setError(null);
    setPreview(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".csv")) {
      setFile(null);
      setError("Please choose a .csv file.");
      return;
    }
    if (f.size > MAX_MB * 1024 * 1024) {
      setFile(null);
      setError(`File is too large. The maximum size is ${MAX_MB} MB.`);
      return;
    }
    setFile(f);
    runPreview(f);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    pickFile(e.dataTransfer.files?.[0]);
  };

  const effectiveMode =
    mode === "auto" ? (mapping.rating || mapping.discount ? "rules" : "anomaly") : mode;

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setProgress(0);
    setError(null);
    setResult(null);
    try {
      const res = await uploadCsv(file, { mapping, mode }, setProgress);
      setResult(res);
      setFile(null);
      setPreview(null);
      if (inputRef.current) inputRef.current.value = "";
      if (onUploaded) await onUploaded(res);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3 className="card-title">Upload any CSV</h3>
          <p className="card-sub">
            Any delimiter (comma, semicolon, tab) and any columns. AARC detects what each column
            means and lets you correct it. Max {MAX_MB} MB.
          </p>
        </div>
      </div>

      <div
        className={`dropzone ${dragOver ? "dropzone-active" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          hidden
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        <div className="dropzone-icon">
          <Icon name="upload" size={26} />
        </div>
        {file ? (
          <p>
            <strong>{file.name}</strong> ({(file.size / 1024).toFixed(1)} KB)
          </p>
        ) : (
          <p>
            <strong>Drag and drop a CSV here</strong>, or click to browse
          </p>
        )}
      </div>

      {previewing && <p className="card-sub" style={{ marginTop: 12 }}>Reading columns...</p>}

      {/* ---------- Column mapping ---------- */}
      {preview && (
        <div className="mapping">
          <h4 className="mapping-title">Check how your columns are used</h4>
          <p className="card-sub">
            Pick "Not used" for anything that does not apply. With no rating or discount, AARC
            switches to statistical outlier detection across your numeric columns.
          </p>

          <div className="mapping-grid">
            {ROLE_FIELDS.map((f) => (
              <label key={f.key} className="field">
                <span className="field-label">{f.label}</span>
                <select
                  className="input"
                  value={mapping[f.key] ?? ""}
                  onChange={(e) => setMapping((m) => ({ ...m, [f.key]: e.target.value || null }))}
                >
                  <option value="">Not used</option>
                  {preview.columns.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name} ({c.kind})
                    </option>
                  ))}
                </select>
                <span className="field-hint">{f.hint}</span>
              </label>
            ))}

            <label className="field">
              <span className="field-label">Scoring method</span>
              <select className="input" value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <span className="field-hint">Will use: {MODE_NAMES[effectiveMode]}</span>
            </label>
          </div>

          <div className="table-wrap sample-table">
            <table className="table">
              <thead>
                <tr>
                  {preview.columns.map((c) => (
                    <th key={c.name}>
                      {c.name} <span className="kind-tag">{c.kind}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.preview_rows.map((row, i) => (
                  <tr key={i}>
                    {preview.columns.map((c) => (
                      <td key={c.name}>{row[c.name]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="upload-actions">
        <button
          className="btn"
          onClick={handleUpload}
          disabled={!file || !preview || previewing || uploading}
        >
          {uploading ? (progress < 100 ? `Uploading... ${progress}%` : "Processing...") : "Upload and analyse"}
        </button>
      </div>

      {uploading && (
        <div className="progress">
          <div className="progress-bar" style={{ width: `${progress}%` }} />
        </div>
      )}

      {error && <div className="alert alert-error">{error}</div>}

      {result && (
        <div className="alert alert-success">
          <div>
            <strong>{result.filename}</strong> analysed with <strong>{MODE_NAMES[result.mode]}</strong>{" "}
            scoring: {result.rows.processed} of {result.rows.total} rows kept ({result.rows.dropped}{" "}
            dropped). Low {result.risk_summary.Low} / Medium {result.risk_summary.Medium} / High{" "}
            {result.risk_summary.High}.
          </div>
          {result.cleaning_notes.length > 0 && (
            <details className="notes">
              <summary>Cleaning notes ({result.cleaning_notes.length})</summary>
              <ul>
                {result.cleaning_notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            </details>
          )}
          {onViewDashboard && (
            <button className="btn btn-small" style={{ marginTop: 10 }} onClick={onViewDashboard}>
              View dashboard
            </button>
          )}
        </div>
      )}
    </section>
  );
}
