import { definePlugin, PanelSection, PanelSectionRow, ButtonItem, ToggleField, DropdownItem, staticClasses } from "@decky/ui";
import { callable } from "@decky/api";
import { FaVideo } from "react-icons/fa";
import { useEffect, useState } from "react";

const getStatus = callable<[], any>("get_status");
const saveSettings = callable<[any], any>("save_settings");
const startStream = callable<[any], any>("start_stream");
const stopStream = callable<[], any>("stop_stream");
const clearLog = callable<[], any>("clear_log");

const FPS = [
  { data: "60", label: "60 fps" },
  { data: "75", label: "75 fps" },
  { data: "90", label: "90 fps" },
  { data: "100", label: "100 fps" },
];
const BITRATE = ["8","10","12","14","16","18","20","24","30","32","40"].map((v) => ({ data: v, label: `${v} Mbps` }));
const KEYFRAME = [{ data: "1", label: "1 s" }, { data: "3", label: "3 s" }];
const PRESET = ["ultrafast","superfast","veryfast","faster","fast","medium"].map((v) => ({ data: v, label: v }));
const ROTATION = [
  { data: "none", label: "None" },
  { data: "90", label: "90°" },
  { data: "180", label: "180°" },
  { data: "270", label: "270°" },
];

const defaults = () => ({ rotation: "270", bitrate: "40", fps: "100", keyframe_seconds: "3", preset: "ultrafast", screen_off: false });

function Content() {
  const [status, setStatus] = useState<any>({ running: false, log: [], settings: defaults() });
  const [settings, setSettings] = useState<any>(defaults());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const merge = (s: any) => ({ ...defaults(), ...(s || {}) });

  const refresh = async () => {
    try {
      const st = await getStatus();
      if (st) {
        setStatus(st);
        if (st.settings) setSettings(merge(st.settings));
      }
    } catch (e) { console.error(e); }
  };

  useEffect(() => { refresh(); const t = setInterval(refresh, 2000); return () => clearInterval(t); }, []);

  const onSave = async () => {
    setMessage("");
    const r = await saveSettings({ settings });
    setSettings(merge(r || settings));
    setMessage("Settings saved");
    refresh();
  };

  const onStart = async () => {
    setBusy(true); setMessage("Starting...");
    try {
      await saveSettings({ settings });
      const r = await startStream({ settings });
      if (r && r.ok === false) setMessage(`Start error: ${r.error || "unknown"}`);
      else setMessage("Stream started");
    } finally { setBusy(false); setTimeout(refresh, 600); }
  };

  const onStop = async () => {
    setBusy(true); setMessage("Stopping...");
    try { await stopStream(); setMessage("Stop requested"); }
    finally { setBusy(false); setTimeout(refresh, 600); }
  };

  const logText = (status.log || []).slice(-14).join("\n");
  const profile = `kmsgrab · libx264 ${settings.preset} · ${settings.fps} fps · ${settings.bitrate} Mbps · keyframe ${settings.keyframe_seconds}s${settings.screen_off ? " · dim screen" : ""}`;

  return (
    <div>
      <PanelSection title="G2 Bridge">
        <PanelSectionRow>
          <div style={{ fontSize: "13px", fontWeight: 600 }}>{status.running ? "Streaming" : "Idle"}</div>
          <div style={{ fontSize: "11px", opacity: 0.85, marginTop: "4px" }}>{profile}</div>
        </PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy || status.running} onClick={onStart}>Start streaming</ButtonItem></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" disabled={busy || !status.running} onClick={onStop}>Stop</ButtonItem></PanelSectionRow>
        {message ? <PanelSectionRow><div style={{ fontSize: "11px", opacity: 0.9 }}>{message}</div></PanelSectionRow> : null}
      </PanelSection>
      <PanelSection title="Settings">
        <PanelSectionRow><DropdownItem label="Rotation" rgOptions={ROTATION} selectedOption={settings.rotation} onChange={(opt: any) => setSettings({ ...settings, rotation: opt.data })} /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="Frame rate" rgOptions={FPS} selectedOption={settings.fps} onChange={(opt: any) => setSettings({ ...settings, fps: opt.data })} /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="Bitrate" rgOptions={BITRATE} selectedOption={settings.bitrate} onChange={(opt: any) => setSettings({ ...settings, bitrate: opt.data })} /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="Keyframe" rgOptions={KEYFRAME} selectedOption={settings.keyframe_seconds} onChange={(opt: any) => setSettings({ ...settings, keyframe_seconds: opt.data })} /></PanelSectionRow>
        <PanelSectionRow><DropdownItem label="x264 preset" rgOptions={PRESET} selectedOption={settings.preset} onChange={(opt: any) => setSettings({ ...settings, preset: opt.data })} /></PanelSectionRow>
        <PanelSectionRow><ToggleField label="Dim device screen" checked={!!settings.screen_off} onChange={(v: boolean) => setSettings({ ...settings, screen_off: v })} /></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={onSave}>Save settings</ButtonItem></PanelSectionRow>
      </PanelSection>
      <PanelSection title="Log">
        <PanelSectionRow><div style={{ fontSize: "11px", whiteSpace: "pre-wrap", maxHeight: "220px", overflow: "auto", opacity: 0.85 }}>{logText || "(no log yet)"}</div></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={async () => { await clearLog(); refresh(); }}>Clear log</ButtonItem></PanelSectionRow>
      </PanelSection>
    </div>
  );
}

export default definePlugin(() => ({
  name: "G2 Bridge",
  titleView: <div className={staticClasses.Title}>G2 Bridge</div>,
  content: <Content />,
  icon: <FaVideo />,
  onDismount() {},
}));
