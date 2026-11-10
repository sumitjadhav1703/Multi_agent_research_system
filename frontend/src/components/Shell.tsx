import { useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getReady, getUsage } from "../api/client";
import { rememberedRun, useToken } from "../auth/token";
import { IdentityGate } from "./IdentityGate";

const logoSrc = `${import.meta.env.BASE_URL}logo.webp`;

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
  const close = () => setMenuOpen(false);

  return (
    <div className={`shell${menuOpen ? " menu-open" : ""}`}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="chrome no-print">
        <Link className="brand" to="/" onClick={close}>
          <span className="brand-logo" aria-hidden="true">
            <img src={logoSrc} alt="" width="52" height="52" />
          </span>
        </Link>

        {token ? (
          <nav className="nav-pill desktop-nav" aria-label="Primary">
            <NavLink to="/" end className={navClass} onClick={close}>
              Ask
            </NavLink>
            {current ? (
              <>
                <NavLink to={`/runs/${current}`} end className={navClass} onClick={close}>
                  Live
                </NavLink>
                <NavLink to={`/runs/${current}/report`} className={navClass} onClick={close}>
                  Report
                </NavLink>
                <NavLink to={`/runs/${current}/evidence`} className={navClass} onClick={close}>
                  Evidence
                </NavLink>
              </>
            ) : null}
            <NavLink to="/evaluation" className={navClass} onClick={close}>
              Eval
            </NavLink>
            <NavLink to="/usage" className={navClass} onClick={close}>
              Usage
            </NavLink>
          </nav>
        ) : (
          <p className="chrome-title">ResearchMind</p>
        )}

        <div className="chrome-actions">
          <p className="status-pill" title={`Database: ${health.data?.database ?? "unknown"}`}>
            {ready ? "Ready" : health.isPending ? "Waking…" : "Sleeping"}
            {token ? ` · ${allowance(usage.data?.one_use_consumed, usage.data?.one_use_refunded)}` : null}
          </p>
          {token ? (
            <>
              <button type="button" className="menu-button" aria-expanded={menuOpen} aria-controls="mobile-menu" onClick={() => setMenuOpen((o) => !o)}>
                <span className="burger-bar" aria-hidden="true" />
                <span className="burger-bar" aria-hidden="true" />
                <span className="burger-bar" aria-hidden="true" />
                <span className="visually-hidden">Menu</span>
              </button>
              <button type="button" className="ghost-btn desktop-only" onClick={() => clearToken()}>
                Reset
              </button>
            </>
          ) : null}
        </div>
      </header>

      {token ? (
        <>
          <div className="menu-overlay" hidden={!menuOpen} onClick={close} />
          <div id="mobile-menu" className="mobile-menu" hidden={!menuOpen} role="dialog" aria-modal="true" aria-label="Menu">
            <nav className="mobile-nav" aria-label="Mobile">
              <NavLink to="/" end className={mobileNavClass} onClick={close}>
                Ask
              </NavLink>
              {current ? (
                <>
                  <NavLink to={`/runs/${current}`} end className={mobileNavClass} onClick={close}>
                    Live
                  </NavLink>
                  <NavLink to={`/runs/${current}/report`} className={mobileNavClass} onClick={close}>
                    Report
                  </NavLink>
                  <NavLink to={`/runs/${current}/evidence`} className={mobileNavClass} onClick={close}>
                    Evidence
                  </NavLink>
                </>
              ) : null}
              <NavLink to="/evaluation" className={mobileNavClass} onClick={close}>
                Eval
              </NavLink>
              <NavLink to="/usage" className={mobileNavClass} onClick={close}>
                Usage
              </NavLink>
              <button type="button" className="mobile-reset" onClick={() => { clearToken(); close(); }}>
                Reset session
              </button>
            </nav>
          </div>
        </>
      ) : null}

      <main id="main" className="stage">
        {!health.isPending && !ready ? (
          <p className="wake-note" role="status">
            Service is waking up. This can take about a minute on the free host.
          </p>
        ) : null}
        {token ? <Outlet /> : <IdentityGate />}
      </main>
    </div>
  );
}

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "nav-link is-active" : "nav-link";
}

function mobileNavClass({ isActive }: { isActive: boolean }) {
  return isActive ? "mobile-link is-active" : "mobile-link";
}

function allowance(consumed: boolean | undefined, refunded: boolean | undefined): string {
  if (consumed) return "run used";
  if (refunded) return "1 run left";
  if (consumed === false) return "1 run left";
  return "limits";
}
