import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export const GUEST_TOKEN_KEY = "researchmind.guestToken";
export const CURRENT_RUN_KEY = "researchmind.currentRunId";

interface TokenContextValue {
  token: string | null;
  setToken: (value: string | null) => void;
  clearToken: () => void;
}

const TokenContext = createContext<TokenContextValue | null>(null);

export function TokenProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => sessionStorage.getItem(GUEST_TOKEN_KEY));

  const setToken = useCallback((value: string | null) => {
    if (value) sessionStorage.setItem(GUEST_TOKEN_KEY, value);
    else sessionStorage.removeItem(GUEST_TOKEN_KEY);
    setTokenState(value);
  }, []);

  const clearToken = useCallback(() => setToken(null), [setToken]);
  const value = useMemo(() => ({ token, setToken, clearToken }), [token, setToken, clearToken]);
  return <TokenContext.Provider value={value}>{children}</TokenContext.Provider>;
}

export function useToken(): TokenContextValue {
  const value = useContext(TokenContext);
  if (!value) throw new Error("TokenProvider is missing");
  return value;
}

export function rememberRun(runId: string) {
  sessionStorage.setItem(CURRENT_RUN_KEY, runId);
}

export function rememberedRun(): string | null {
  return sessionStorage.getItem(CURRENT_RUN_KEY);
}
