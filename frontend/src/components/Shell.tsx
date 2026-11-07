import { useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getReady, getUsage } from "../api/client";
import { rememberedRun, useToken } from "../auth/token";
import { IdentityGate } from "./IdentityGate";

export function Shell() {
  const { token, clearToken } = useToken();
  const params = useParams();
  const [menuOpen, setMenuOpen] = useState(false);
  const health = useQuery({
    queryKey: ["health", "ready"],
    queryFn: getReady,
    refetchInterval: (query) => (query.state.data?.status === "ready" ? 30000 : 5000),
  });
  const usage = useQuery({
    queryKey: ["usage"],
    enabled: Boolean(token),
    queryFn: () => getUsage(token as string),
  });
  const current = params.runId ?? usage.data?.run_ids.at(-1) ?? rememberedRun();
  const ready = health.data?.status === "ready";

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar no-print">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <div>
            <strong>ResearchMind</strong>
            <span>Research console</span>
          </div>
        </div>
        <div className="button-row">
          <p className="muted">{allowance(usage.data?.one_use_consumed, usage.data?.one_use_refunded)}</p>
          <button type="button" className="menu-button secondary" aria-expanded={menuOpen} aria-controls="sidebar" onClick={() => setMenuOpen((open) => !open)}>
            Menu
          </button>
          {token ? (
            <button type="button" className="secondary" onClick={() => clearToken()}>
              Forget token
            </button>
          ) : null}
        </div>
      </header>
      <div className="workspace">
        <nav id="sidebar" className={menuOpen ? "sidebar open no-print" : "sidebar no-print"} aria-label="Primary">
          <NavLink to="/" onClick={() => setMenuOpen(false)}>
            New research
          </NavLink>
          {current ? (
            <>
              <p className="nav-label">This run</p>
              <NavLink to={`/runs/${current}`} onClick={() => setMenuOpen(false)}>
                Live run
              </NavLink>
              <NavLink to={`/runs/${current}/report`} onClick={() => setMenuOpen(false)}>
                Final report
              </NavLink>
              <NavLink to={`/runs/${current}/evidence`} onClick={() => setMenuOpen(false)}>
                Evidence
              </NavLink>
            </>
          ) : null}
          <p className="nav-label">Account</p>
          <NavLink to="/evaluation" onClick={() => setMenuOpen(false)}>
            Evaluation
          </NavLink>
          <NavLink to="/usage" onClick={() => setMenuOpen(false)}>
            Usage
          </NavLink>
          <p className="nav-label">Later</p>
          <p className="muted">MCP tools are not in this release.</p>
          <p className="meta">Provider health: {ready ? "ready" : "not ready"}</p>
          <p className="meta">Database: {health.data?.database ?? "unknown"}</p>
        </nav>
        <main id="main" className="main">
          {health.isPending ? <p role="status">Checking whether the research service is awake.</p> : null}
          {!health.isPending && !ready ? (
            <p className="banner warning" role="status">
              The research service is not ready. A free host can take a minute to wake up.
            </p>
          ) : null}
          {token ? <Outlet /> : <IdentityGate />}
        </main>
      </div>
    </div>
  );
}

function allowance(consumed: boolean | undefined, refunded: boolean | undefined): string {
  if (consumed) return "Demo run used";
  if (refunded) return "One run available after a refund";
  if (consumed === false) return "One guest run available";
  return "Demo limits";
}
