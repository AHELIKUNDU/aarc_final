import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { RISK_COLORS, formatDate } from "../utils";
import Icon from "./Icons";

function KpiCard({ icon, label, value, sub, tone }) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <div className="kpi-icon">
        <Icon name={icon} size={22} />
      </div>
      <div className="kpi-body">
        <div className="kpi-label">{label}</div>
        <div className="kpi-value">{value}</div>
        <div className="kpi-sub">{sub}</div>
      </div>
    </div>
  );
}

const firstReason = (text) => (text ? text.split(". ")[0].replace(/\.$/, "") : "");

export default function Dashboard({ summary, insights, onViewAll }) {
  if (!summary) return null;

  const { risk_counts: counts, risk_percentages: pct, total_items: total } = summary;

  const pieData = ["Low", "Medium", "High"]
    .map((level) => ({ name: level, value: counts[level] }))
    .filter((d) => d.value > 0);

  const barData = summary.categories.slice(0, 8).map((c) => ({
    category: c.category,
    Low: c.low,
    Medium: c.medium,
    High: c.high,
  }));

  const rd = insights ? insights.risk_drivers : {};
  const drivers = insights
    ? [
        { label: "Low customer rating", value: rd.low_rating, color: RISK_COLORS.High },
        { label: "Heavy discounting", value: rd.heavy_discount, color: RISK_COLORS.Medium },
        { label: "Discount applied", value: rd.discount_applied ?? 0, color: "#f97316" },
        { label: "Price outlier", value: rd.price_outlier, color: "#6366f1" },
        { label: "Statistical outlier", value: rd.statistical_outlier ?? 0, color: "#0891b2" },
      ].filter((d) => d.value > 0)
    : [];

  return (
    <div className="page">
      <p className="page-sub">
        Showing <strong>{summary.upload.filename}</strong> · uploaded{" "}
        {formatDate(summary.upload.uploaded_at)}
      </p>

      {/* ---------- KPI row ---------- */}
      <div className="kpi-grid">
        <KpiCard icon="database" tone="blue" label="Total Data" value={total} sub="items analysed" />
        <KpiCard
          icon="alertTriangle"
          tone="red"
          label="High Risks"
          value={counts.High}
          sub={`${summary.high_risk_percentage}% of all items`}
        />
        <KpiCard
          icon="alertCircle"
          tone="amber"
          label="Medium Risks"
          value={counts.Medium}
          sub={`${pct.Medium}% of all items`}
        />
        <KpiCard
          icon="activity"
          tone="slate"
          label="Avg Risk Score"
          value={summary.average_risk_score}
          sub="out of 100"
        />
      </div>

      {/* ---------- Risk mix bar ---------- */}
      <section className="card">
        <div className="card-head">
          <h3 className="card-title">Portfolio risk mix</h3>
        </div>
        <div className="mixbar">
          {["Low", "Medium", "High"].map(
            (lvl) =>
              counts[lvl] > 0 && (
                <div
                  key={lvl}
                  className="mixbar-seg"
                  style={{ width: `${pct[lvl]}%`, background: RISK_COLORS[lvl] }}
                  title={`${lvl}: ${counts[lvl]} (${pct[lvl]}%)`}
                >
                  {pct[lvl] >= 9 ? `${lvl} ${pct[lvl]}%` : ""}
                </div>
              )
          )}
        </div>
      </section>

      {/* ---------- Charts ---------- */}
      <div className="grid grid-1-2">
        <section className="card">
          <div className="card-head">
            <h3 className="card-title">Risk distribution</h3>
          </div>
          <div className="donut-wrap">
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={pieData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={70}
                  outerRadius={100}
                  paddingAngle={2}
                  stroke="none"
                >
                  {pieData.map((d) => (
                    <Cell key={d.name} fill={RISK_COLORS[d.name]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="donut-center">
              <div className="donut-total">{total}</div>
              <div className="donut-label">items</div>
            </div>
          </div>
          <div className="legend">
            {["Low", "Medium", "High"].map((lvl) => (
              <span key={lvl} className="legend-item">
                <span className="legend-dot" style={{ background: RISK_COLORS[lvl] }} />
                {lvl} <strong>{counts[lvl]}</strong>
              </span>
            ))}
          </div>
        </section>

        <section className="card">
          <div className="card-head">
            <div>
              <h3 className="card-title">Risk by category</h3>
              <p className="card-sub">Items per risk level, riskiest categories first</p>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={Math.max(260, barData.length * 46)}>
            <BarChart
              data={barData}
              layout="vertical"
              margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
              barSize={20}
            >
              <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
              <XAxis type="number" allowDecimals={false} fontSize={12} stroke="#94a3b8" />
              <YAxis type="category" dataKey="category" width={110} fontSize={12} stroke="#64748b" />
              <Tooltip cursor={{ fill: "#f1f5f9" }} />
              <Bar dataKey="Low" stackId="risk" fill={RISK_COLORS.Low} />
              <Bar dataKey="Medium" stackId="risk" fill={RISK_COLORS.Medium} />
              <Bar dataKey="High" stackId="risk" fill={RISK_COLORS.High} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      {/* ---------- Insights ---------- */}
      {insights && (
        <div className="grid grid-3">
          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Key insights</h3>
            </div>
            <ul className="insight-list">
              {insights.headlines.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </section>

          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Risk drivers</h3>
              <p className="card-sub">Items affected</p>
            </div>
            <div className="drivers">
              {drivers.length === 0 && <p className="card-sub">No risk drivers were triggered.</p>}
              {drivers.map((d) => (
                <div key={d.label} className="driver">
                  <div className="driver-top">
                    <span>{d.label}</span>
                    <strong>{d.value}</strong>
                  </div>
                  <div className="driver-track">
                    <div
                      className="driver-fill"
                      style={{ width: `${total ? (d.value * 100) / total : 0}%`, background: d.color }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <h3 className="card-title">Recommendations</h3>
            </div>
            <ul className="insight-list">
              {insights.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </section>
        </div>
      )}

      {/* ---------- Top risks ---------- */}
      {insights && insights.top_risks.length > 0 && (
        <section className="card">
          <div className="card-head">
            <div>
              <h3 className="card-title">Top 5 highest-risk items</h3>
              <p className="card-sub">The most urgent items to review</p>
            </div>
            {onViewAll && (
              <button className="btn btn-small btn-ghost" onClick={onViewAll}>
                View full register
              </button>
            )}
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Category</th>
                  <th>Score</th>
                  <th>Level</th>
                  <th>Main reason</th>
                </tr>
              </thead>
              <tbody>
                {insights.top_risks.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.product_name}</strong>
                    </td>
                    <td>{r.category}</td>
                    <td>
                      <div className="score-cell">
                        <span>{r.risk_score}</span>
                        <div className="score-bar">
                          <div
                            style={{ width: `${r.risk_score}%`, background: RISK_COLORS[r.risk_level] }}
                          />
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className={`badge badge-${r.risk_level.toLowerCase()}`}>{r.risk_level}</span>
                    </td>
                    <td className="reasoning-cell">{firstReason(r.reasoning)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
