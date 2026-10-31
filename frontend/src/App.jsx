import { useCallback, useEffect, useState } from "react";
import Dashboard from "./components/Dashboard";
import DataTable from "./components/DataTable";
import Icon from "./components/Icons";
import Upload from "./components/Upload";
import UploadHistory from "./components/UploadHistory";
import {
  checkHealth,
  getErrorMessage,
  getInsights,
  getSummary,
  getUploads,
} from "./services/api";

const NAV = [
  { id: "overview", label: "Overview", icon: "grid", title: "Risk Overview" },
  { id: "upload", label: "Data Upload", icon: "upload", title: "Data Upload" },
  { id: "register", label: "Risk Register", icon: "list", title: "Risk Register" },
];

export default function App() {
  const [view, setView] = useState("overview");
  const [backendStatus, setBackendStatus] = useState("checking"); // checking | online | offline

  const [uploads, setUploads] = useState([]);
  const [uploadId, setUploadId] = useState(null);
  const [summary, setSummary] = useState(null);
  const [insights, setInsights] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const connect = useCallback(() => {
    setBackendStatus("checking");
    checkHealth()
      .then(() => setBackendStatus("online"))
      .catch(() => setBackendStatus("offline"));
  }, []);

  // Load the upload list, then summary + insights for the chosen upload
  const refresh = useCallback(async (preferredId) => {
    setLoading(true);
    setError(null);
    try {
      const list = (await getUploads()).filter((u) => u.status === "processed");
      setUploads(list);
      if (list.length === 0) {
        setUploadId(null);
        setSummary(null);
        setInsights(null);
        setView("upload");
        return;
      }
      const id = preferredId ?? list[0].id;
      const [s, i] = await Promise.all([getSummary(id), getInsights(id)]);
      setUploadId(id);
      setSummary(s);
      setInsights(i);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    connect();
  }, [connect]);

  useEffect(() => {
    if (backendStatus === "online") refresh();
  }, [backendStatus, refresh]);

  const current = NAV.find((n) => n.id === view);

  return (
    <div className="layout">
      {/* ================= Sidebar ================= */}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo">A</div>
          <div>
            <div className="brand-name">AARC</div>
            <div className="brand-tag">AI Analyst and Reasoning Catalyst</div>
          </div>
        </div>

        <nav className="nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${view === n.id ? "active" : ""}`}
              onClick={() => setView(n.id)}
            >
              <Icon name={n.icon} size={18} />
              <span>{n.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className={`status-pill status-${backendStatus}`}>
            <span className="status-dot" />
            {backendStatus === "checking" && "Connecting..."}
            {backendStatus === "online" && "Backend online"}
            {backendStatus === "offline" && "Backend offline"}
          </div>
          {backendStatus === "offline" && (
            <button className="btn btn-small" onClick={connect}>
              Retry
            </button>
          )}
        </div>
      </aside>

      {/* ================= Main ================= */}
      <div className="main">
        <header className="topbar">
          <h1 className="topbar-title">{current.title}</h1>
          {uploads.length > 0 && (
            <div className="topbar-right">
              <label className="topbar-label" htmlFor="upload-select">
                Dataset
              </label>
              <select
                id="upload-select"
                className="input"
                value={uploadId ?? ""}
                onChange={(e) => refresh(Number(e.target.value))}
              >
                {uploads.map((u) => (
                  <option key={u.id} value={u.id}>
                    #{u.id} · {u.filename}
                  </option>
                ))}
              </select>
            </div>
          )}
        </header>

        <main className="content">
          {backendStatus === "offline" && (
            <div className="alert alert-error">
              Could not reach the API. Start the backend from the backend folder with{" "}
              <code>python -m uvicorn app.main:app --reload</code>.
            </div>
          )}
          {error && <div className="alert alert-error">{error}</div>}

          {view === "upload" && (
            <div className="page">
              <Upload
                onUploaded={(res) => refresh(res.upload_id)}
                onViewDashboard={() => setView("overview")}
              />
              <UploadHistory
                uploads={uploads}
                activeId={uploadId}
                onSelect={(id) => {
                  refresh(id);
                  setView("overview");
                }}
              />
            </div>
          )}

          {view !== "upload" && !summary && (
            <div className="card empty-state">
              {loading ? (
                <p>Loading results...</p>
              ) : (
                <>
                  <p>No data yet. Upload a CSV to see your risk dashboard.</p>
                  <button className="btn" onClick={() => setView("upload")}>
                    Go to Data Upload
                  </button>
                </>
              )}
            </div>
          )}

          {view === "overview" && summary && (
            <Dashboard summary={summary} insights={insights} onViewAll={() => setView("register")} />
          )}

          {view === "register" && summary && (
            <div className="page">
              <DataTable
                key={uploadId}
                uploadId={uploadId}
                categories={summary.categories.map((c) => c.category)}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
