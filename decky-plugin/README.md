# G2 Bridge — Decky Loader plugin (autonomous)

Плагин для Decky Loader, чтобы запускать G2 Bridge (стрим на DJI Goggles Integra/G2) в **Game Mode** на GNU/Linux (Steam Deck). Плагин **автономный**: включает нужный Python-код (`goggles_bridge`, `stream_linux.py`, `pyusb`) и не требует внешнего каталога проекта/venv.

## Что делает
- Кнопки **Start/Stop** для эталонного профиля (`kmsgrab` + `libx264 ultrafast`, 100 fps, keyframe 3s).
- Настройки: битрейт (по умолчанию 40 Мбит/с), поворот, опция **Steam Deck black screen** (гашение экрана Deck при подключении очков).
- Показывает статус и последние строки лога.

Бэкенд запускает стрим от root (Decky backend с `"flags": ["root"]`) с `--stop-file`.

## Установка / обновление
1. Убедитесь, что Decky Loader установлен.
2. Скопируйте папку `decky-plugin` в плагины Decky как `G2Bridge`:
   ```bash
   sudo cp -r "/var/home/sevara/Documents/Default Project/g2-bridge/decky-plugin/." ~/homebrew/plugins/G2Bridge/
   ```
   (или установите папку `decky-plugin` как `G2Bridge` в `~/homebrew/plugins/`)
3. Перезагрузите плагины в Decky Loader (Reload plugins) или перезапустите Decky/Game Mode. Плагин появится в Quick Access (… ) → плагины.

## Требования (системные)
- **ffmpeg** в системе (для захвата `kmsgrab` и кодирования `libx264`).
- USB-доступ к очкам (`libusb`/права; Decky backend работает от root) и очки в режиме *More → DJI Virtual Flight*.
- Для `kmsgrab` нужен доступ к DRM/KMS (обычно root — обеспечивается плагином).

Python-зависимости (`pyusb`) и код моста (`goggles_bridge`, `stream_linux.py`) bundled внутри `backend/`.

## Сборка фронтенда (если нужно)
В `dist/` лежит готовый фронтенд. Если меняли `src/` и нужно пересобрать (нужны Node.js/npm):
```bash
cd decky-plugin
npm install
npm run build
```
Затем скопируйте обновлённую папку плагина в `~/homebrew/plugins/G2Bridge`.

## Примечания
- Эталонный профиль: 100 fps, keyframe 3s, rotate 270, libx264 ultrafast. Битрейт/поворот и *Steam Deck black screen* настраиваются в UI.
- Логи стрима: `~/.local/state/g2-bridge/logs/`.
- *Steam Deck black screen* удерживает яркость на 0 (с восстановлением при Stop), чтобы стрим в очки продолжал идти.
