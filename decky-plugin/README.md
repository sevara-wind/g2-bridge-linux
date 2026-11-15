# G2 Bridge — Decky Plugin (Game Mode)

Новый автономный плагин для **Decky Loader**, повторяющий основные настройки десктопного приложения G2 Bridge для запуска стрима в **Game Mode** (Steam Deck / GNU/Linux).

## Возможности
- Start / Stop стриминга (`kmsgrab` → `libx264`, USB PC route)
- Настройки (как в десктопном приложении): **Rotation**, **Frame rate (60/75/90/100)**, **Bitrate (8–40 Mbps)**, **Keyframe (1/3 s)**, **x264 preset**, **Dim device screen**
- Сохранение настроек, статус, лог, очистка лога

## Зависимости (на хосте)
- Decky Loader
- `python3` и `ffmpeg` с `kmsgrab`
- Права root/доступ к DRM для `kmsgrab` (плагин запускается с `flags: ["root"]`)
- Очки DJI Goggles 2 / Integra в режиме `More → DJI Virtual Flight`

## Установка (из репозитория)
Замените старый плагин новой версией:
```bash
sudo rm -rf "$HOME/homebrew/plugins/G2Bridge" && sudo cp -a "/var/home/sevara/Documents/Default Project/g2-bridge/decky-plugin" "$HOME/homebrew/plugins/G2Bridge"
```
При необходимости:
```bash
sudo chown -R "$USER:$USER" "$HOME/homebrew/plugins/G2Bridge"
```
Затем перезапустите Decky Loader (или игровой режим).

## Разработка frontend
`dist/index.js` включён для установки без сборки. Исходники в `src/index.tsx`. Для пересборки UI (на машине с Node.js):
```bash
cd decky-plugin
npm install
npm run build
```

## Примечания
- Бэкенд автономный: `backend/goggles_bridge`, `backend/scripts/stream_linux.py`, `backend/py_modules` входят в плагин.
- Для обновления логики стрима синхронизируйте файлы в `backend/` (в репозитории они поддерживаются вместе с остальным проектом).
