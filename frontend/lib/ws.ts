// WebSocket client with auto-reconnect. Streams health/mode/broker events.

export type WsMessage = { topic: string; data: any };

function wsBackendBase(): string {
  const explicit = process.env.NEXT_PUBLIC_BACKEND_URL;
  if (explicit) return explicit;
  // Docker proxy mode: REST is same-origin; WebSocket still hits the mapped backend port.
  if (typeof window !== "undefined") {
    return `http://${window.location.hostname}:8000`;
  }
  return "http://127.0.0.1:8000";
}

export function connectWs(onMessage: (msg: WsMessage) => void): () => void {
  const wsUrl = wsBackendBase().replace(/^http/, "ws") + "/ws";

  let socket: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;

  const open = () => {
    socket = new WebSocket(wsUrl);
    socket.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data));
      } catch {
        /* ignore malformed frames */
      }
    };
    socket.onclose = () => {
      if (!closed) retry = setTimeout(open, 2000);
    };
    socket.onerror = () => socket?.close();
  };

  open();

  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    socket?.close();
  };
}
