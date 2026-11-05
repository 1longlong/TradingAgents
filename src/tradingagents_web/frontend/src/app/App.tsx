import { Navigate, Route, Routes } from "react-router-dom";

import { HistoryDetailPage } from "../pages/HistoryDetailPage";
import { HistoryPage } from "../pages/HistoryPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/history" replace />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/history/:artifactId" element={<HistoryDetailPage />} />
      <Route path="*" element={<Navigate to="/history" replace />} />
    </Routes>
  );
}
