import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AccessApp } from "./access/routes";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AccessApp />
  </StrictMode>,
);
