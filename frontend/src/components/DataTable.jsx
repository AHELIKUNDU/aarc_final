import { useEffect, useMemo, useState } from "react";
import { getErrorMessage, getRisks } from "../services/api";
import { RISK_COLORS, downloadCsv } from "../utils";
import Icon from "./Icons";

const PAGE_SIZE = 10;
const EXPORT_BATCH = 1000; // backend maximum per request
const EXPORT_MAX = 100000; // safety cap for CSV export

const LEVEL_OPTIONS = [
  { value: "risky", label: "Medium + High" },
  { value: "High", label: "High only" },
  { value: "Medium", label: "Medium only" },
  { value: "Low", label: "Low only" },
  { value: "all", label: "All items" },
];

const COLUMNS = [
  { key: "product_name", label: "Product", sortable: true },
  { key: "category", label: "Category", sortable: true },
  { key: "rating", label: "Rating", sortable: true },
  { key: "price", label: "Price", sortable: true },
  { key: "discount", label: "Discount", sortable: true },
  { key: "risk_score", label: "Score", sortable: true },
  { key: "risk_level", label: "Level", sortable: false },
  { key: "reasoning", label: "Reasoning / Insights", sortable: false },
];

const dash = (v, fmt = (x) => x) => (v === null || v === undefined ? "—" : fmt(v));

export default function DataTable({ uploadId, categories = [] }) {
  const [level, setLevel] = useState("risky");
  const [category, setCategory] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("risk_score");
  const [order, setOrder] = useState("desc");
  const [page, setPage] = useState(0);

  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);

  // Debounce the search box
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Filter + sort params (everything except paging)
  const baseParams = useMemo(() => {
    const p = { upload_id: uploadId, sort_by: sortBy, order };
    if (level === "all") p.include_low = true;
    else if (level !== "risky") p.risk_level = level;
    if (category) p.category = category;
    if (search) p.search = search;
    return p;
  }, [uploadId, level, category, search, sortBy, order]);

  // Fetch rows whenever a filter, sort or page changes
  useEffect(() => {
    let ignore = false;
    setLoading(true);
    getRisks({ ...baseParams, skip: page * PAGE_SIZE, limit: PAGE_SIZE })
      .then((res) => {
        if (!ignore) {
          setData(res);
          setError(null);
        }
      })
      .catch((err) => !ignore && setError(getErrorMessage(err)))
      .finally(() => !ignore && setLoading(false));
    return () => {
      ignore = true;
    };
  }, [baseParams, page]);

  const toggleSort = (key) => {
    if (key === sortBy) {
      setOrder(order === "desc" ? "asc" : "desc");
    } else {
      setSortBy(key);
      setOrder(key === "product_name" || key === "category" ? "asc" : "desc");
    }
    setPage(0);
  };

  // Export every row matching the current filters (fetched in batches)
  const handleExport = async () => {
    setExporting(true);
    try {
      const rows = [];
      let skip = 0;
      let total = Infinity;
      while (skip < total && skip < EXPORT_MAX) {
        const res = await getRisks({ ...baseParams, skip, limit: EXPORT_BATCH });
        rows.push(...res.items);
        total = res.total;
        skip += EXPORT_BATCH;
      }
      downloadCsv(`aarc_risk_register_upload_${uploadId}.csv`, rows, COLUMNS);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const from = data.total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min((page + 1) * PAGE_SIZE, data.total);

  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3 className="card-title">Risk register</h3>
          <p className="card-sub">Every item with the reasoning behind its score</p>
        </div>
        <button className="btn btn-small btn-ghost" onClick={handleExport} disabled={exporting || !data.total}>
          <Icon name="download" size={14} /> {exporting ? "Exporting..." : "Export CSV"}
        </button>
      </div>

      {/* ---- Filters ---- */}
      <div className="filters">
        <input
          className="input"
          type="search"
          placeholder="Search product name..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        <select
          className="input"
          value={level}
          onChange={(e) => {
            setLevel(e.target.value);
            setPage(0);
          }}
        >
          {LEVEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          className="input"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setPage(0);
          }}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* ---- Table ---- */}
      <div className={`table-wrap ${loading ? "table-loading" : ""}`}>
        <table className="table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={col.sortable ? "sortable" : ""}
                  onClick={col.sortable ? () => toggleSort(col.key) : undefined}
                >
                  {col.label}
                  {col.sortable && sortBy === col.key && (order === "desc" ? " ▼" : " ▲")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 && !loading && (
              <tr>
                <td colSpan={COLUMNS.length} className="empty-row">
                  No items match these filters.
                </td>
              </tr>
            )}
            {data.items.map((r) => (
              <tr key={r.id}>
                <td>
                  <strong>{r.product_name}</strong>
                </td>
                <td>{r.category}</td>
                <td>{dash(r.rating, (v) => v.toFixed(1))}</td>
                <td>{dash(r.price, (v) => v.toLocaleString())}</td>
                <td>{dash(r.discount, (v) => `${v}%`)}</td>
                <td>
                  <div className="score-cell">
                    <span>{r.risk_score}</span>
                    <div className="score-bar">
                      <div style={{ width: `${r.risk_score}%`, background: RISK_COLORS[r.risk_level] }} />
                    </div>
                  </div>
                </td>
                <td>
                  <span className={`badge badge-${r.risk_level.toLowerCase()}`}>{r.risk_level}</span>
                </td>
                <td className="reasoning-cell">{r.reasoning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ---- Pagination ---- */}
      <div className="pagination">
        <span className="pagination-info">
          Showing {from}-{to} of {data.total}
        </span>
        <div className="pagination-buttons">
          <button className="btn btn-small btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="pagination-page">
            Page {page + 1} / {totalPages}
          </span>
          <button
            className="btn btn-small btn-ghost"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage(page + 1)}
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
