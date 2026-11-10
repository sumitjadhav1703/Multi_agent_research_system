import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { createGuest, readEnv } from "../api/client";
import { useToken } from "../auth/token";
import { ErrorText } from "./ui";

interface TurnstileRenderOptions {
  sitekey: string;
  callback: (token: string) => void;
  "expired-callback"?: () => void;
  "error-callback"?: () => void;
}

interface TurnstileApi {
  render: (element: HTMLElement, options: TurnstileRenderOptions) => string | undefined;
  reset?: (widgetId?: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const TURNSTILE_SCRIPT_ID = "turnstile-api";

/** Inject the Turnstile script once per page, however often the gate mounts. */
function loadTurnstile() {
  if (document.getElementById(TURNSTILE_SCRIPT_ID)) return;
  const script = document.createElement("script");
  script.id = TURNSTILE_SCRIPT_ID;
  script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
  script.async = true;
  script.defer = true;
  document.head.appendChild(script);
}

export function IdentityGate() {
  const { setToken } = useToken();
  const siteKey = readEnv("VITE_TURNSTILE_SITE_KEY");
  const [verification, setVerification] = useState("");
  const [widgetNote, setWidgetNote] = useState("");
  const widgetIdRef = useRef<string | undefined>(undefined);
  const refreshVerification = useCallback(() => {
    setVerification("");
    const api = window.turnstile;
    if (typeof api?.reset !== "function") return;
    if (widgetIdRef.current) api.reset(widgetIdRef.current);
    else api.reset();
  }, []);
  const mutation = useMutation({
    mutationFn: (turnstileToken: string) => createGuest(turnstileToken),
    onSuccess: (body) => setToken(body.guest_token),
    onError: () => refreshVerification(),
  });

  useEffect(() => {
    if (!siteKey) return;
    loadTurnstile();
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      const node = document.getElementById("turnstile-widget");
      if (window.turnstile && node && node.childElementCount === 0) {
        const widgetId = window.turnstile.render(node, {
          sitekey: siteKey,
          callback: setVerification,
          "expired-callback": refreshVerification,
          "error-callback": refreshVerification,
        });
        widgetIdRef.current = typeof widgetId === "string" ? widgetId : undefined;
        window.clearInterval(timer);
      }
      if (attempts > 66) { // ~20s
        setWidgetNote("Verification widget did not load. Paste a token if you have one.");
        window.clearInterval(timer);
      }
    }, 300);
    return () => {
      window.clearInterval(timer);
    };
  }, [refreshVerification, siteKey]);

  return (
    <section className="panel stack gate-panel">
      <h1>Enter demo</h1>
      <p>One guest session. Pass the check below, then ask one public research question.</p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (!verification.trim()) return;
          mutation.mutate(verification.trim());
        }}
      >
        {siteKey ? <div id="turnstile-widget" /> : null}
        {!siteKey ? (
          <p className="banner warning" role="status">
            Turnstile site key is missing on this build, so the widget cannot load. Add{" "}
            <code>VITE_TURNSTILE_SITE_KEY</code> on Vercel and redeploy.
          </p>
        ) : null}
        {widgetNote ? (
          <p className="banner warning" role="status">
            {widgetNote}
          </p>
        ) : null}
        {!siteKey || widgetNote ? (
          <label className="field">
            <span>Verification token</span>
            <input
              type="text"
              name="turnstile_token"
              autoComplete="off"
              value={verification}
              onChange={(event) => setVerification(event.target.value)}
              placeholder="Paste token"
            />
          </label>
        ) : (
          <input type="hidden" name="turnstile_token" value={verification} />
        )}
        <ErrorText error={mutation.error} />
        <button type="submit" disabled={mutation.isPending || verification.trim().length === 0}>
          {mutation.isPending ? "Checking…" : "Continue"}
        </button>
      </form>
    </section>
  );
}
