import { useEffect, useState } from "react";
import {
  ButtonItem,
  DropdownItem,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  definePlugin,
  staticClasses,
} from "@decky/ui";
import { callable } from "@decky/api";
import { FaVideo } from "react-icons/fa";

const getStatus = callable<[], any>("get_status");
const getSettings = callable<[], any>("get_settings");
const saveSettings = callable<[any], any>("save_settings");
const startStream = callable<[any], any>("start_stream");
const stopStream = callable<[], any>("stop_stream");
const clearLog = callable<[], any>("clear_log");

const bitrateOptions = ["8","10","12","16","20","24","30","32","40"].map(v => ({ data: v, label: `${v} Mbps` }));
const rotationOptions = [
  { data: "none", label: "None" },
  { data: "90", label: "90°" },
  { data: "180", label: "180°" },
  { data: "270", label: "270°" },
];

function Content() {
  const [status, setStatus] = useState<any>({ running: false, log: [], settings: {} });
  const [settings, setSettings] = useState<any>({ bitrate: "40", rotation: "270", screen_off: false });
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const st = await getStatus();
      setStatus(st || { running: false, log: [], settings: {} });
      if (st?.settings) setSettings({ bitrate: st.settings.bitrate || "40", rotation: st.settings.rotation || "270", screen_off: !!st.settings.screen_off });
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, []);

  const onStart = async () => {
    setBusy(true);
    try {
      await saveSettings(settings);
      await startStream(settings);
    } finally {
      setBusy(false);
      setTimeout(refresh, 500);
    }
  };

  const onStop = async () => {
    setBusy(true);
    try {
      await stopStream();
    } finally {
      setBusy(false);
      setTimeout(refresh, 500);
    }
  };

  const logText = (status.log || []).slice(-12).join("\n");

  return (
    <PanelSection title="G2 Bridge (DJI Goggles)">
      <PanelSectionRow>
        <div style={{ fontSize: "12px", opacity: 0.9 }}>
          Status: <b>{status.running ? "Running" : "Stopped"}</b>
          {status.exit_code !== null && status.exit_code !== undefined ? ` (exit ${status.exit_code})` : ""}
        </div>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy || status.running} onClick={onStart}>
          Start Stream
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy || !status.running} onClick={onStop}>
          Stop Stream
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <DropdownItem
          label="Bitrate"
          rgOptions={bitrateOptions}
          selectedOption={settings.bitrate || "40"}
          onChange={(opt: any) => setSettings({ ...settings, bitrate: opt.data })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Rotation"
          rgOptions={rotationOptions}
          selectedOption={settings.rotation || "270"}
          onChange={(opt: any) => setSettings({ ...settings, rotation: opt.data })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Steam Deck black screen"
          checked={!!settings.screen_off}
          onChange={(v: boolean) => setSettings({ ...settings, screen_off: v })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={async () => { await saveSettings(settings); refresh(); }}>
          Save Settings
        </ButtonItem>
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem layout="below" onClick={async () => { await clearLog(); refresh(); }}>
          Clear Log
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <div style={{ fontSize: "11px", whiteSpace: "pre-wrap", maxHeight: "180px", overflow: "auto", opacity: 0.85 }}>
          {logText || "(no log yet)"}
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

export default definePlugin(() => ({
  name: "G2 Bridge",
  titleView: <div className={staticClasses.Title}>G2 Bridge</div>,
  content: <Content />,
  icon: <FaVideo />,
  onDismount() {},
}));
