// REQ-WEB-001/008/010/021, ADR-003: keep the workspace behind the reference analysis sheet.
import { useEffect, useRef } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "./AppShell";
import { BacktestPage } from "../pages/BacktestPage";
import { AuditPage } from "../pages/AuditPage";
import { ComparisonPage } from "../pages/ComparisonPage";
import { HistoryDetailPage } from "../pages/HistoryDetailPage";
import { HistoryPage } from "../pages/HistoryPage";
import { JournalPage } from "../pages/JournalPage";
import { LiveRunPage } from "../pages/LiveRunPage";
import { NewAnalysisPage } from "../pages/NewAnalysisPage";
import { OverviewPage } from "../pages/OverviewPage";

export function App() {
  const location = useLocation();
  const previous = useRef(
    location.pathname === "/new"
      ? { ...location, pathname: "/overview", search: "", hash: "" }
      : location,
  );
  const sheet = location.pathname === "/new";
  useEffect(() => {
    if (!sheet) previous.current = location;
  }, [location, sheet]);
  return (
    <AppShell>
      <Routes location={sheet ? previous.current : location}>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/history/:artifactId" element={<HistoryDetailPage />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/backtest/:runId" element={<BacktestPage />} />
        <Route path="/runs/:runId" element={<LiveRunPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/comparison" element={<ComparisonPage />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Routes>
      {sheet ? (
        <NewAnalysisPage
          returnTo={previous.current.pathname + previous.current.search}
        />
      ) : null}
    </AppShell>
  );
}
