"use client";
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

export function useTheme() {
  const [theme, setTheme] = useState<"board" | "paper">("board");
  useEffect(() => { setTheme(document.documentElement.dataset.theme === "paper" ? "paper" : "board"); }, []);
  const toggle = () => {
    const n = theme === "board" ? "paper" : "board"; setTheme(n);
    if (n === "paper") document.documentElement.dataset.theme = "paper"; else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("verdict.theme", n); } catch { /* ignore */ }
  };
  return { theme, toggle };
}
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return <button onClick={toggle} className="btn btn-ghost btn-icon" aria-label={`Switch to ${theme === "board" ? "paper" : "board"} theme`} title="Board / Paper">{theme === "board" ? <Sun size={15} /> : <Moon size={15} />}</button>;
}
