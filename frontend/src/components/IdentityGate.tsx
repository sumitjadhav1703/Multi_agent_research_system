import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { createGuest, readEnv } from "../api/client";
import { useToken } from "../auth/token";
import { ErrorText } from "./ui";

interface TurnstileApi {
  render: (element: HTMLElement, options: { sitekey: string; callback: (token: string) => void }) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

export function IdentityGate() {
  const { setToken } = useToken();
  const siteKey = readEnv("VITE_TURNSTILE_SITE_KEY");
  const [verification, setVerification] = useState("");
  const [widgetNote, setWidgetNote] = useState("");
  const mutation = useMutation({
    mutationFn: (turnstileToken: string) => createGuest(turnstileToken),
    onSuccess: (body) => setToken(body.guest_token),
  });

  useEffect(() => {
    if (!siteKey) return;
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      const node = document.getElementById("turnstile-widget");
      if (window.turnstile && node && node.childElementCount === 0) {
        window.turnstile.render(node, { sitekey: siteKey, callback: setVerification });
        window.clearInterval(timer);
      }
      if (attempts > 20) {
        setWidgetNote("The verification widget did not load. Paste a token if you already have one.");
        window.clearInterval(timer);
      }
    }, 300);
    return () => {
      window.clearInterval(timer);
      script.remove();
    };
  }, [siteKey]);

  return (
    <section className="panel stack">
      <h1>Verify to continue</h1>
      <p>
        This demo issues one guest identity after a Cloudflare Turnstile check. The token stays in this
        browser tab and is sent as a bearer header, never in the page address.
      </p>
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
            No public Turnstile site key is configured for this build. The server still decides whether
            the verification token is valid.
          </p>
        ) : null}
        {widgetNote ? (
          <p className="banner warning" role="status">
            {widgetNote}
          </p>
        ) : null}
        <label className="field">
          <span>Verification token</span>
          <input
            type="text"
            name="turnstile_token"
            autoComplete="off"
            value={verification}
            onChange={(event) => setVerification(event.target.value)}
          />
        </label>
        <ErrorText error={mutation.error} />
        <button type="submit" disabled={mutation.isPending || verification.trim().length === 0}>
          {mutation.isPending ? "Checking…" : "Continue"}
        </button>
      </form>
    </section>
  );
}
