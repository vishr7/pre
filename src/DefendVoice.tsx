
import { useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";

function VoiceControls({ base }: { base: string }) {
  const conversation = useConversation();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [demoKey, setDemoKey] = useState("");

  async function startDefense() {
    setError("");

    if (!demoKey.trim()) {
      setError("Please enter the demo access key.");
      return;
    }

    setLoading(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      stream.getTracks().forEach((track) => track.stop());

      // Use PRE's configured backend URL, or the local backend.
      const apiBase =
        base.trim().replace(/\/+$/, "") || "http://localhost:8000";

      const response = await fetch(`${apiBase}/defend/signed-url`, {
        headers: {
          "X-PRE-Demo-Key": demoKey.trim(),
        },
      });

      if (!response.ok) {
        if (response.status === 401) {
          throw new Error("Invalid demo access key.");
        }
        if (response.status === 503) {
          throw new Error("Demo access is not configured on the backend.");
        }
        throw new Error(`Could not get signed URL (HTTP ${response.status}).`);
      }

      const data: { signed_url: string } = await response.json();

      await conversation.startSession({
        signedUrl: data.signed_url,
        connectionType: "websocket",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h3>PRE Defend — Voice Examiner</h3>

      <label>
        Demo access key
        <input
          type="password"
          autoComplete="off"
          value={demoKey}
          onChange={(event) => setDemoKey(event.target.value)}
          placeholder="Enter demo access key"
          disabled={loading || conversation.status !== "disconnected"}
        />
      </label>

      <p>Status: {conversation.status}</p>

      <button
        onClick={startDefense}
        disabled={loading || conversation.status !== "disconnected"}
      >
        {loading ? "Starting..." : "Start Voice Defense"}
      </button>

      <button
        onClick={() => conversation.endSession()}
        disabled={conversation.status === "disconnected"}
      >
        End Conversation
      </button>

      {error && <p role="alert">{error}</p>}
    </div>
  );
}

export default function DefendVoice({ base }: { base: string }) {
  return (
    <ConversationProvider>
      <VoiceControls base={base} />
    </ConversationProvider>
  );
}
