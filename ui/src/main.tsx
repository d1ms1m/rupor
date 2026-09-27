import "@fontsource-variable/inter";
import "./styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { applyCachedTheme, enableMicaIfSupported } from "./lib/theme";

applyCachedTheme();
void enableMicaIfSupported();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
