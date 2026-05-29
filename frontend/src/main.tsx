import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { WebSocketProvider } from "./hooks/useWebSocket";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <WebSocketProvider>
      <App />
    </WebSocketProvider>
  </React.StrictMode>,
);
