import { Theme } from "@radix-ui/themes";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { accentOptions, theme, type AccentId } from "../theme/tokens";

export type Mode = "light" | "dark" | "system";
const KEY = "mrforge-theme";
const ACCENT_KEY = "mrforge-accent";

function storedAccent(): AccentId {
  try {
    const v = localStorage.getItem(ACCENT_KEY);
    if (accentOptions.some((o) => o.id === v)) return v as AccentId;
  } catch {
    /* blocked storage: use the default */
  }
  return theme.accentColor;
}

function stored(): Mode {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    /* storage can be blocked: fall back to the computer's setting */
  }
  return "system";
}

type Ctx = {
  mode: Mode;
  appearance: "light" | "dark";
  setMode: (m: Mode) => void;
  toggle: () => void;
  accent: AccentId; // provisional palette choice (UI redesign, D-08)
  setAccent: (a: AccentId) => void;
};
const ThemeContext = createContext<Ctx | null>(null);

export function useAppTheme(): Ctx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useAppTheme needs a ThemeProvider");
  return ctx;
}

/** Light / dark / follow the computer, remembered between visits. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<Mode>(stored);
  const [accent, setAccentState] = useState<AccentId>(storedAccent);
  const [systemDark, setSystemDark] = useState(() => matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const q = matchMedia("(prefers-color-scheme: dark)");
    const on = () => setSystemDark(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  const appearance = mode === "system" ? (systemDark ? "dark" : "light") : mode;
  const value = useMemo<Ctx>(
    () => ({
      mode,
      appearance,
      setMode: (m) => {
        setModeState(m);
        try {
          localStorage.setItem(KEY, m);
        } catch {
          /* not remembered; still works for this visit */
        }
      },
      accent,
      setAccent: (a) => {
        setAccentState(a);
        try {
          localStorage.setItem(ACCENT_KEY, a);
        } catch {
          /* not remembered; still works for this visit */
        }
      },
      toggle: () => {
        const next = appearance === "dark" ? "light" : "dark";
        setModeState(next);
        try {
          localStorage.setItem(KEY, next);
        } catch {
          /* ignore */
        }
      },
    }),
    [mode, appearance, accent],
  );
  return (
    <ThemeContext.Provider value={value}>
      <Theme {...theme} accentColor={accent} appearance={appearance} style={{ minHeight: "100vh" }}>
        {children}
      </Theme>
    </ThemeContext.Provider>
  );
}
