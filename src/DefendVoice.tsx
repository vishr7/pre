
import { useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";

function VoiceControls() {
  const conversation = useConversation();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function startDefense() {
    setError("");
    setLoading(true);

    try {
      // Ask permission to use the microphone.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      stream.getTracks().forEach((track) => track.stop());

      // Get a signed URL from our FastAPI backend.
      const response = await fetch("http://localhost:8000/defend/signed-url");

      if (!response.ok) {
        throw new Error("Could not get the ElevenLabs signed URL.");
      }

      const data = await response.json();

      // Start the voice conversation.
      conversation.startSession({
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

export default function DefendVoice() {
  return (
    <ConversationProvider>
      <VoiceControls />
    </ConversationProvider>
  );
}
