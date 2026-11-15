(function (SP_REACT, DFL) {
  const { useState, useEffect } = SP_REACT;
  const { definePlugin, PanelSection, PanelSectionRow, ButtonItem, ToggleField, DropdownItem, staticClasses } = DFL;

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

  const FPS = [
    { data: "60", label: "60 fps" },
    { data: "75", label: "75 fps" },
    { data: "90", label: "90 fps" },
    { data: "100", label: "100 fps" },
  ];
  const BITRATE = ["8","10","12","14","16","18","20","24","30","32","40"].map((v) => ({ data: v, label: v + " Mbps" }));
  const KEYFRAME = [
    { data: "1", label: "1 s" },
    { data: "3", label: "3 s" },
  ];
  const PRESET = ["ultrafast","superfast","veryfast","faster","fast","medium"].map((v) => ({ data: v, label: v }));
  const ROTATION = [
    { data: "none", label: "None" },
    { data: "90", label: "90°" },
    { data: "180", label: "180°" },
    { data: "270", label: "270°" },
  ];

  function defaults() {
    return { rotation: "270", bitrate: "40", fps: "100", keyframe_seconds: "3", preset: "ultrafast", screen_off: false };
  }

  function Content({ serverApi }) {
    const [status, setStatus] = useState({ running: false, exit_code: null, log: [], settings: defaults() });
    const [settings, setSettings] = useState(defaults());
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState("");

    const mergeSettings = (s) => {
      const d = defaults();
      const out = Object.assign({}, d, s || {});
      return out;
    };

    const refresh = async () => {
      try {
        const st = await call(serverApi, "get_status", {});
        if (st && !st._rpcError) {
          setStatus(st);
          if (st.settings) setSettings(mergeSettings(st.settings));
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
      const r = await call(serverApi, "save_settings", { settings });
      if (r && r._rpcError) setMessage("Save error: " + r._rpcError);
      else { setSettings(mergeSettings(r || settings)); setMessage("Settings saved"); }
      await refresh();
    };

    const onStart = async () => {
      setBusy(true);
      setMessage("Starting...");
      try {
        await call(serverApi, "save_settings", { settings });
        const r = await call(serverApi, "start_stream", { settings });
        if (r && r._rpcError) setMessage("Start error: " + r._rpcError);
        else if (r && r.ok === false) setMessage("Start error: " + (r.error || "unknown"));
        else setMessage("Stream started");
      } finally {
        setBusy(false);
        setTimeout(refresh, 600);
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
        setTimeout(refresh, 600);
      }
    };

    const logText = (status.log || []).slice(-14).join("\n");
    const running = !!status.running;
    const profile = "kmsgrab · libx264 " + settings.preset + " · " + settings.fps + " fps · " + settings.bitrate + " Mbps · keyframe " + settings.keyframe_seconds + "s" + (settings.screen_off ? " · dim screen" : "");

    return SP_REACT.createElement("div", null,
      SP_REACT.createElement(PanelSection, { title: "G2 Bridge" },
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement("div", { style: { fontSize: "13px", fontWeight: "600" } }, running ? "Streaming" : "Idle"),
          SP_REACT.createElement("div", { style: { fontSize: "11px", opacity: 0.85, marginTop: "4px" } }, profile)
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(ButtonItem, { layout: "below", disabled: busy || running, onClick: onStart }, "Start streaming")
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(ButtonItem, { layout: "below", disabled: busy || !running, onClick: onStop }, "Stop")
        ),
        message ? SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement("div", { style: { fontSize: "11px", opacity: 0.9 } }, message)
        ) : null
      ),
      SP_REACT.createElement(PanelSection, { title: "Settings" },
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(DropdownItem, {
            label: "Rotation", rgOptions: ROTATION, selectedOption: settings.rotation,
            onChange: (opt) => setSettings(Object.assign({}, settings, { rotation: opt.data }))
          })
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(DropdownItem, {
            label: "Frame rate", rgOptions: FPS, selectedOption: settings.fps,
            onChange: (opt) => setSettings(Object.assign({}, settings, { fps: opt.data }))
          })
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(DropdownItem, {
            label: "Bitrate", rgOptions: BITRATE, selectedOption: settings.bitrate,
            onChange: (opt) => setSettings(Object.assign({}, settings, { bitrate: opt.data }))
          })
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(DropdownItem, {
            label: "Keyframe", rgOptions: KEYFRAME, selectedOption: settings.keyframe_seconds,
            onChange: (opt) => setSettings(Object.assign({}, settings, { keyframe_seconds: opt.data }))
          })
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(DropdownItem, {
            label: "x264 preset", rgOptions: PRESET, selectedOption: settings.preset,
            onChange: (opt) => setSettings(Object.assign({}, settings, { preset: opt.data }))
          })
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(ToggleField, {
            label: "Dim device screen", checked: !!settings.screen_off,
            onChange: (v) => setSettings(Object.assign({}, settings, { screen_off: !!v }))
          })
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(ButtonItem, { layout: "below", onClick: onSave }, "Save settings")
        )
      ),
      SP_REACT.createElement(PanelSection, { title: "Log" },
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement("div", { style: { fontSize: "11px", whiteSpace: "pre-wrap", maxHeight: "220px", overflow: "auto", opacity: 0.85 } }, logText || "(no log yet)")
        ),
        SP_REACT.createElement(PanelSectionRow, null,
          SP_REACT.createElement(ButtonItem, { layout: "below", onClick: async () => { await call(serverApi, "clear_log", {}); refresh(); } }, "Clear log")
        )
      )
    );
  }

  return definePlugin((serverApi) => ({
    name: "G2 Bridge",
    titleView: SP_REACT.createElement("div", { className: staticClasses.Title }, "G2 Bridge"),
    content: SP_REACT.createElement(Content, { serverApi }),
    icon: SP_REACT.createElement("span", null, "G2"),
    onDismount() {},
  }));
})(window.SP_REACT, window.DFL);
