// Axios setup + one function per backend endpoint.
import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
});

// Turns any axios error into a readable message for the UI
export function getErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (detail) return typeof detail === "string" ? detail : JSON.stringify(detail);
  if (error?.request) return "Cannot reach the AARC server. Is the backend running?";
  return error?.message || "Something went wrong.";
}

// --- Health ---
export const checkHealth = () => api.get("/health").then((r) => r.data);

// --- Upload ---
// 1) Preview: send only the first 256 KB so even huge files preview instantly.
//    Returns columns, sample rows and the auto-detected column mapping.
export const previewCsv = (file) => {
  const form = new FormData();
  form.append("file", file.slice(0, 256 * 1024), file.name);
  return api.post("/upload/preview", form).then((r) => r.data);
};

// 2) Upload: mapping = { product_name, category, rating, price, discount } (column names or null)
//    mode = "auto" | "rules" | "anomaly"
export const uploadCsv = (file, { mapping, mode } = {}, onProgress) => {
  const form = new FormData();
  form.append("file", file);
  if (mapping) form.append("mapping", JSON.stringify(mapping));
  form.append("mode", mode || "auto");
  return api
    .post("/upload", form, {
      timeout: 10 * 60 * 1000, // big files can take minutes to process
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total));
      },
    })
    .then((r) => r.data);
};

// --- Analytics (Steps 5 and 6 use these) ---
// uploadId is optional: when undefined the backend uses the latest upload.
export const getUploads = () => api.get("/analytics/uploads").then((r) => r.data);

export const getSummary = (uploadId) =>
  api.get("/analytics/summary", { params: { upload_id: uploadId } }).then((r) => r.data);

// params: { upload_id, risk_level, include_low, category, search, sort_by, order, skip, limit }
export const getRisks = (params = {}) =>
  api.get("/analytics/risks", { params }).then((r) => r.data);

export const getInsights = (uploadId) =>
  api.get("/analytics/insights", { params: { upload_id: uploadId } }).then((r) => r.data);

export default api;
