import { lazy, Suspense, useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { TokenProvider } from "./auth/token";
import { Shell } from "./components/Shell";
import { RunWorkspace } from "./hooks/runChannelContext";
import { EvidencePage } from "./pages/EvidencePage";
import { LiveRunPage } from "./pages/LiveRunPage";
import { NewResearchPage } from "./pages/NewResearchPage";
import { ReportPage } from "./pages/ReportPage";
import { UsagePage } from "./pages/UsagePage";
import { ApiError } from "./api/client";

// recharts is only used here; keep it out of the main chunk.
const EvaluationPage = lazy(() => import("./pages/EvaluationPage").then((m) => ({ default: m.EvaluationPage })));

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (count, error) =>
              count < 1 && !(error instanceof ApiError && [401, 403, 404].includes(error.status)),
            refetchOnWindowFocus: true,
          },
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
        <Route path="runs/:runId" element={<RunWorkspace />}>
          <Route index element={<LiveRunPage />} />
          <Route path="report" element={<ReportPage />} />
          <Route path="evidence" element={<EvidencePage />} />
        </Route>
        <Route
          path="evaluation"
          element={
            <Suspense fallback={<p role="status">Loading.</p>}>
              <EvaluationPage />
            </Suspense>
          }
        />
        <Route path="usage" element={<UsagePage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <AppProviders>
      <BrowserRouter basename="/app">
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  );
}
