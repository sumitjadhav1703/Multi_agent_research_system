import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { TokenProvider } from "./auth/token";
import { Shell } from "./components/Shell";
import { EvaluationPage } from "./pages/EvaluationPage";
import { EvidencePage } from "./pages/EvidencePage";
import { LiveRunPage } from "./pages/LiveRunPage";
import { NewResearchPage } from "./pages/NewResearchPage";
import { ReportPage } from "./pages/ReportPage";
import { UsagePage } from "./pages/UsagePage";

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: true },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <TokenProvider>{children}</TokenProvider>
    </QueryClientProvider>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<NewResearchPage />} />
        <Route path="runs/:runId" element={<LiveRunPage />} />
        <Route path="runs/:runId/report" element={<ReportPage />} />
        <Route path="runs/:runId/evidence" element={<EvidencePage />} />
        <Route path="evaluation" element={<EvaluationPage />} />
        <Route path="usage" element={<UsagePage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <AppProviders>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  );
}
