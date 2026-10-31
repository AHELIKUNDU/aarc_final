export const RISK_COLORS = { Low: "#16a34a", Medium: "#f59e0b", High: "#dc2626" };

// Backend sends UTC timestamps without a timezone suffix; treat them as UTC.
export function formatDate(iso) {
  if (!iso) return "—";
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function downloadCsv(filename, rows, columns) {
  const esc = (v) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = columns.map((c) => c.label).join(",");
  const lines = rows.map((r) => columns.map((c) => esc(r[c.key])).join(","));
  const blob = new Blob(["\ufeff" + [header, ...lines].join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
