(function (SP_REACT, DFL) {
  const { useState, useEffect } = SP_REACT;
  const { definePlugin, PanelSection, PanelSectionRow, ButtonItem, ToggleField, TextField, staticClasses } = DFL;

  function call(serverApi, method, args) {
    return serverApi.callPluginMethod(method, args || {}).then((res) => {
      if (res && res.success) return res.result;
      if (res && !res.success) return { _rpcError: res.result || "call failed" };
      return res ? res.result : null;
    }).catch((e) => {
      console.error("G2Bridge call error", method, e);
      return { _rpcError: String(e) };
    });
  }

  function Content({ serverApi }) {
    const [status, setStatus] = useState({ running: false, exit_code: null, log: [], settings: {} });
    const [settings, setSettings] = useState({ bitrate: "40", rotation: "270", screen_off: false });
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState("");

    const refresh = async () => {
      try {
        const st = await call(serverApi, "get_status", {});
        if (st && !st._rpcError) {
          setStatus(st);
          if (st.settings) setSettings({ bitrate: st.settings.bitrate || "40", rotation: st.settings.rotation || "270", screen_off: !!st.settings.screen_off });
        } else if (st && st._rpcError) {
          setMessage("Status error: " + st._rpcError);
        }
      } catch (e) {
        console.error(e);
      }
    };

    useEffect(() => {
      refresh();
      const t = setInterval(refresh, 2000);
      return () => clearInterval(t);
    }, []);

    const onSave = async () => {
      setMessage("");
      const r = await call(serverApi, "save_settings", settings);
      if (r && r._rpcError) setMessage("Save error: " + r._rpcError);
      else setMessage("Settings saved");
      await refresh();
    };

    const onStart = async () => {
      setBusy(true);
      setMessage("Starting...");
      try {
        await call(serverApi, "save_settings", settings);
        const r = await call(serverApi, "start_stream", settings);
        if (r && r._rpcError) {
          setMessage("Start error: " + r._rpcError);
        } else if (r && r.ok === false) {
          setMessage("Start failed: " + (r.error || "unknown error"));
        } else if (r && r.ok) {
          setMessage("Started");
        } else {
          setMessage("Start requested");
        }
      } finally {
        setBusy(false);
        setTimeout(refresh, 800);
      }
    };

    const onStop = async () => {
      setBusy(true);
      setMessage("Stopping...");
      try {
        const r = await call(serverApi, "stop_stream", {});
        if (r && r._rpcError) setMessage("Stop error: " + r._rpcError);
        else setMessage("Stop requested");
      } finally {
        setBusy(false);
        setTimeout(refresh, 800);
      }
    };

    const logText = (status.log || []).slice(-14).join("\n");
    const running = !!status.running;

    return SP_REACT.createElement(PanelSection, { title: "DJI Goggles Stream" },
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement("div", { style: { fontSize: "12px" } },
          "Status: ", SP_REACT.createElement("b", null, running ? "Running" : "Stopped"),
          (status.exit_code !== null && status.exit_code !== undefined && !running) ? ` (exit ${status.exit_code})` : ""
        )
      ),
      message ? SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement("div", { style: { fontSize: "11px", whiteSpace: "pre-wrap", opacity: 0.95 } }, message)
      ) : null,
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(ButtonItem, { layout: "below", disabled: busy || running, onClick: onStart }, "Start Stream")
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(ButtonItem, { layout: "below", disabled: busy || !running, onClick: onStop }, "Stop Stream")
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(TextField, {
          label: "Bitrate (8,10,12,16,20,24,30,32,40)",
          value: String(settings.bitrate || "40"),
          onChange: (e) => {
            const v = e && e.target ? e.target.value : e;
            setSettings({ ...settings, bitrate: String(v) });
          }
        })
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(TextField, {
          label: "Rotation (none,90,180,270)",
          value: String(settings.rotation || "270"),
          onChange: (e) => {
            const v = e && e.target ? e.target.value : e;
            setSettings({ ...settings, rotation: String(v) });
          }
        })
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(ToggleField, {
          label: "Steam Deck black screen",
          checked: !!settings.screen_off,
          onChange: (v) => setSettings({ ...settings, screen_off: !!v })
        })
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(ButtonItem, { layout: "below", onClick: onSave }, "Save Settings")
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement(ButtonItem, { layout: "below", onClick: async () => { await call(serverApi, "clear_log", {}); refresh(); } }, "Clear Log")
      ),
      SP_REACT.createElement(PanelSectionRow, null,
        SP_REACT.createElement("div", { style: { fontSize: "11px", whiteSpace: "pre-wrap", maxHeight: "220px", overflow: "auto", opacity: 0.85 } }, logText || "(no log yet)")
      )
    );
  }

  return definePlugin((serverApi) => {
    return {
      title: SP_REACT.createElement("div", { className: staticClasses ? staticClasses.Title : "staticClassesTitle" }, "G2 Bridge"),
      content: SP_REACT.createElement(Content, { serverApi }),
      icon: SP_REACT.createElement("span", null, "G2"),
      onDismount() {}
    };
  });
})(SP_REACT, DFL);
