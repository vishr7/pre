import { useState } from "react";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import { AudioLines, LoaderCircle, Mic, ShieldCheck } from "lucide-react";

function VoiceControls({ base }: { base: string }) {
  const conversation = useConversation();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const connected = conversation.status === "connected";
  const active = connected || conversation.status === "connecting" || loading;
  const speaking = connected && conversation.isSpeaking;
  const status = error || conversation.status === "error"
    ? { label: "Error", tone: "error" }
    : loading || conversation.status === "connecting"
      ? { label: "Connecting", tone: "connecting" }
      : speaking
        ? { label: "Speaking", tone: "speaking" }
        : connected
          ? { label: "Connected", tone: "connected" }
          : { label: "Disconnected", tone: "disconnected" };

  async function startDefense() {
    setError("");

    setLoading(true);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());

      // Use PRE's configured backend URL, or the local backend.
      const apiBase = base.trim().replace(/\/+$/, "") || "http://localhost:8000";

      const response = await fetch(`${apiBase}/defend/signed-url`);

      if (!response.ok) {
        if (response.status === 500 || response.status === 503) {
          throw new Error("ElevenLabs is not configured on the backend.");
        }
        throw new Error(`Could not get signed URL (HTTP ${response.status}).`);
      }

      const data: { signed_url: string } = await response.json();

      await conversation.startSession({
        signedUrl: data.signed_url,
        connectionType: "websocket",
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.name === "NotAllowedError"
            ? "Microphone access was denied. Allow microphone access in your browser settings and try again."
            : err.message
          : "Something went wrong while starting the conversation.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className={`defend-voice-card${active ? " is-active" : ""}${speaking ? " is-speaking" : ""}`} aria-labelledby="defend-voice-title">
      <div className="defend-voice-topline">
        <span className="defend-voice-kicker"><ShieldCheck size={14} aria-hidden="true" /> RESEARCH PRACTICE</span>
        <span className={`defend-voice-status ${status.tone}`} role="status" aria-live="polite">
          <span className="defend-voice-status-dot" aria-hidden="true" />{status.label}
        </span>
      </div>

      <div className="defend-voice-intro">
        <div className={`defend-voice-orb${active ? " active" : ""}${speaking ? " speaking" : ""}`} aria-hidden="true">
          <span className="defend-voice-orb-halo" />
          <span className="defend-voice-wave"><i /><i /><i /><i /><i /></span>
          {speaking ? <AudioLines size={25} strokeWidth={1.8} /> : <Mic size={25} strokeWidth={1.8} />}
        </div>
        <div>
          <h3 id="defend-voice-title">AI Voice Examiner</h3>
          <p>Practice defending your research in a live conversation with an AI examiner.</p>
        </div>
      </div>

      <div className="defend-voice-actions">
        <button
          className="defend-voice-start"
          onClick={startDefense}
          disabled={loading || (conversation.status !== "disconnected" && conversation.status !== "error") || !!error}
        >
          {loading || conversation.status === "connecting" ? <LoaderCircle className="defend-voice-spinner" size={16} aria-hidden="true" /> : <Mic size={16} aria-hidden="true" />}
          {loading || conversation.status === "connecting" ? "Connecting…" : "Start Voice Defense"}
        </button>
        <button
          className="defend-voice-end"
          onClick={() => { void conversation.endSession(); }}
          disabled={!connected}
        >
          End Conversation
        </button>
      </div>

      <div className="defend-voice-footer">
        <span className="defend-voice-mic-note"><Mic size={12} aria-hidden="true" /> Your browser will ask for microphone access when you start.</span>
        <span className="defend-voice-secure"><ShieldCheck size={12} aria-hidden="true" /> Secure ElevenLabs connection</span>
      </div>

      {error && <p className="defend-voice-error" role="alert">{error}</p>}
      {!error && conversation.status === "error" && conversation.message && <p className="defend-voice-error" role="alert">{conversation.message}</p>}
      {!error && conversation.status === "connecting" && <p className="defend-voice-hint" role="status">Connecting to your examiner. This can take a few seconds.</p>}
    </section>
  );
}

export default function DefendVoice({ base }: { base: string }) {
  return (
    <ConversationProvider>
      <VoiceControls base={base} />
    </ConversationProvider>
  );
}
