import { Theme } from "@radix-ui/themes";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { paletteCss, palettes, theme, type PaletteId } from "../theme/tokens";

export type Mode = "light" | "dark" | "system";
const KEY = "mrforge-theme";
const PALETTE_KEY = "mrforge-palette";

function storedPalette(): PaletteId {
  try {
    const v = localStorage.getItem(PALETTE_KEY);
    if (palettes.some((p) => p.id === v)) return v as PaletteId;
  } catch {
    /* blocked storage: use the default */
  }
  return palettes[0].id;
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
  palette: PaletteId; // provisional palette choice (UI redesign, D-08, D-16)
  setPalette: (p: PaletteId) => void;
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
  const [palette, setPaletteState] = useState<PaletteId>(storedPalette);
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
      palette,
      setPalette: (p) => {
        setPaletteState(p);
        try {
          localStorage.setItem(PALETTE_KEY, p);
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
    [mode, appearance, palette],
  );
  const current = palettes.find((p) => p.id === palette) ?? palettes[0];
  return (
    <ThemeContext.Provider value={value}>
      <style>{paletteCss()}</style>
      <Theme
        {...theme}
        accentColor={current.accent}
        grayColor={current.gray}
        data-palette={current.id}
        appearance={appearance}
        style={{ minHeight: "100vh" }}
      >
        {children}
      </Theme>
    </ThemeContext.Provider>
  );
}
