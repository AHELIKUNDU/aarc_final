import { formatDate } from "../utils";

export default function UploadHistory({ uploads, activeId, onSelect }) {
  if (!uploads.length) return null;
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h3 className="card-title">Upload history</h3>
          <p className="card-sub">Pick a previous upload to view its dashboard.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>File</th>
              <th>Uploaded</th>
              <th>Rows kept</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {uploads.map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td>
                  <strong>{u.filename}</strong>
                </td>
                <td>{formatDate(u.uploaded_at)}</td>
                <td>
                  {u.processed_rows} / {u.total_rows}
                </td>
                <td style={{ textAlign: "right" }}>
                  {u.id === activeId ? (
                    <span className="badge badge-info">Current</span>
                  ) : (
                    <button className="btn btn-small btn-ghost" onClick={() => onSelect(u.id)}>
                      View
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
