import { Navigate, Route, Routes } from "react-router-dom";

import { HistoryDetailPage } from "../pages/HistoryDetailPage";
import { HistoryPage } from "../pages/HistoryPage";
import { BacktestPage } from "../pages/BacktestPage";
import { BacktestRunPage } from "../pages/BacktestRunPage";
import { LiveRunPage } from "../pages/LiveRunPage";
import { NewAnalysisPage } from "../pages/NewAnalysisPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/history" replace />} />
      <Route path="/history" element={<HistoryPage />} />
      <Route path="/history/:artifactId" element={<HistoryDetailPage />} />
      <Route path="/new" element={<NewAnalysisPage />} />
      <Route path="/backtest" element={<BacktestPage />} />
      <Route path="/backtest/:runId" element={<BacktestRunPage />} />
      <Route path="/runs/:runId" element={<LiveRunPage />} />
      <Route path="*" element={<Navigate to="/history" replace />} />
    </Routes>
  );
}
