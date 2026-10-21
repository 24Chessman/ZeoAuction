import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/bricolage-grotesque/opsz.css";
import "@fontsource-variable/geist-mono";
import "./styles/index.css";
import { App } from "./app/App";
import { setTransport } from "./lib/api/http";
import { useMocks } from "./lib/config";
import { mockServer, startMockActivity } from "./lib/mock";

if (useMocks) {
  setTransport(mockServer().handle);
  startMockActivity();
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
