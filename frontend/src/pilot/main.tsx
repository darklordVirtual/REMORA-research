import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../styles.css";
import { PilotApp } from "./PilotApp";

// styles.css switches palettes on the `.dark` class; the pilot follows the OS.
const setTheme = (dark: boolean) => document.documentElement.classList.toggle("dark", dark);
const mq = window.matchMedia("(prefers-color-scheme: dark)");
setTheme(mq.matches);
mq.addEventListener("change", (e) => setTheme(e.matches));

const queryClient = new QueryClient();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <PilotApp />
    </QueryClientProvider>
  </StrictMode>,
);
