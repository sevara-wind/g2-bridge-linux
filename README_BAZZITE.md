# g2-bridge на Steam Deck / Bazzite

Основано на проекте [Ammaar-Alam/g2-bridge](https://github.com/Ammaar-Alam/g2-bridge) (автор: Ammaar Alam). Здесь собраны Linux/Bazzite/Steam Deck-адаптации и доработки поверх upstream.

## Коротко

Официальный `Ammaar-Alam/g2-bridge` умеет **захватывать и кодировать видео только на Windows и macOS**. Linux в upstream есть только на уровне USB-транспорта: libusb, udev-правило и `tools/research/probe_goggles.py` работают, а `scripts/stream_desktop.py` — нет.

В этой копии добавлен Linux-слой, который использует тот же протокол, рукопожатие и пакетизатор g2-bridge:

- `scripts/stream_linux.py` — тестовая картинка, файл, V4L2-устройство или рабочий стол;
- **portal ScreenCast** — рекомендуемый путь для GNOME Wayland: курсор включён, root не нужен, работает и в Flatpak;
- `kmsgrab` — резервный путь для случая, когда portal/PipeWire недоступны;
- `flatpak/` — готовый манифест приложения;
- `setup_bazzite.sh` — создаёт `.venv` и ставит PyUSB из локального wheel без сети.

Прошивка очков не меняется. Используется стоковый режим **More → DJI Virtual Flight**, как и в upstream.

> Проверенная upstream версия прошивки Integra — `01.09.00.00` (наша `v01.09.0000`). **Не обновляйте прошивку очков.**

## Что работает

| Источник | Команда | Статус |
|---|---|---|
| Тестовая картинка | `--source testsrc` | работает |
| Видеофайл (зациклен) | `--source file --file clip.mp4` | работает |
| Аналоговый вход / USB-граббер | `--source v4l2 --device /dev/video0` | работает |
| Рабочий стол через portal | `--source desktop` | рекомендуется, курсор есть |
| Рабочий стол через kmsgrab | `--desktop-capture kmsgrab` | резервный, нужен root |

USB-путь и протокол те же, что в upstream: VID/PID `2ca3:0020`, интерфейс MI04, bulk-пакеты по 978 байт, heartbeat 500 мс, лимит кадра ~56 КБ.

## 1. Установка на Bazzite

Выполняйте в **Konsole на самом Steam Deck** (не внутри Flatpak-песочницы OpenCode).

```bash
cd ~/Documents/Default\ Project/g2-bridge
./setup_bazzite.sh
```

Скрипт:

1. проверяет `python3`;
2. создаёт `.venv`;
3. ставит `PyUSB==1.3.1` из `vendor/` (интернет не нужен);
4. проверяет FFmpeg, GStreamer и portal;
5. печатает дальнейшие команды.

Если `python3 -m venv` падает из-за отсутствия `ensurepip` (частая ситуация на Fedora Atomic), поставьте `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Если нет FFmpeg (нужен только для `testsrc`, `v4l2`, `file` и `kmsgrab`; portal без него работает):

```bash
sudo rpm-ostree install ffmpeg
sudo systemctl reboot
```

Для portal нужны GStreamer tools и плагины. На Bazzite они обычно уже есть. Проверка:

```bash
command -v gst-launch-1.0
gst-inspect-1.0 pipewiresrc >/dev/null && echo pipewiresrc OK
gst-inspect-1.0 x264enc >/dev/null && echo x264enc OK
gst-inspect-1.0 vaapih264enc >/dev/null && echo vaapih264enc OK
```

Нужен хотя бы один из `x264enc`/`vaapih264enc`. Если оба отсутствуют:

```bash
sudo rpm-ostree install gstreamer1-plugins-good gstreamer1-plugins-bad-free gstreamer1-plugins-ugly-free
sudo systemctl reboot
```

## 2. Доступ к USB (udev)

Один раз:

```bash
sudo cp scripts/linux/60-dji-goggles.rules /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger
```

На Fedora группы `plugdev` обычно нет. Правило использует `TAG+="uaccess"`, этого достаточно для локальной сессии. Если пробу запускаете по SSH и получаете `Access denied`:

```bash
sudo groupadd -r plugdev
sudo usermod -aG plugdev "$USER"
# перелогиниться
```

Либо для первой проверки просто запустите пробу через `sudo`.

## 3. Подключение очков

Важно: **Steam Deck должен быть USB-хостом**, а очки — устройством.

- Кабель USB-C → USB-A (адаптер) + USB-A → USB-C, либо powered USB-C hub с USB-A-портом.
- Прямой C-to-C кабель может перевернуть роли: очки станут хостом, Deck их не увидит (та же проблема описана в upstream для Mac).
- Очки: включить → **More → DJI Virtual Flight**.
- Не запускайте одновременно DJI Fly / прошивальщик.

Проверка:

```bash
lsusb | grep 2ca3
# должно быть: ID 2ca3:0020 DJI ...
```

## 4. Проба (без видео)

```bash
.venv/bin/python tools/research/probe_goggles.py --descriptors-only
.venv/bin/python tools/research/probe_goggles.py
```

Ожидаемая идентификация Integra:

```text
E3T ZV901
DJI Goggles Integra
```

Затем режим симулятора и тестовое видео:

```bash
.venv/bin/python tools/research/probe_goggles.py --simulator
.venv/bin/python tools/research/probe_goggles.py --test-video --seconds 20
```

`--test-video` отправляет встроенный тестовый поток. Если он прошёл — USB и протокол в порядке.

## 5. Рабочий стол: portal (рекомендуется)

На GNOME Wayland это лучший путь: xdg-desktop-portal показывает диалог выбора экрана, сам встраивает курсор и отдаёт готовый PipeWire-поток. Root не нужен.

```bash
.venv/bin/python scripts/stream_linux.py --source desktop
```

То же явно:

```bash
.venv/bin/python scripts/stream_linux.py \
    --source desktop --desktop-capture portal \
    --capture-fps 60 --bitrate-mbps 10
```

При первом запуске выберите **весь экран / монитор** в диалоге GNOME. Курсор будет виден в очках.

Проверить команду без запуска:

```bash
.venv/bin/python scripts/stream_linux.py --source desktop --print-command
```

`--print-command` без `--pipewire-node` показывает шаблон `path=<portal-node>`: portal выбирает node во время диалога.

Если portal уже открыт и вы знаете PipeWire node id:

```bash
pw-dump | grep -n 'node.name\|media.class'
.venv/bin/python scripts/stream_linux.py --source desktop \
    --desktop-capture portal --pipewire-node 42
```

### Portal: настройки

- `--portal-rotate 90|180|270` — если композитор отдал поток боком (обычно не требуется, GNOME отдаёт логический экран).
- `--portal-encoder auto|x264|vaapi` — по умолчанию `auto`: сначала `x264enc`, затем `vaapih264enc`.
  Для принудительного GStreamer/x264:
  `scripts/stream_linux.py --source desktop --desktop-capture portal --portal-encoder x264`.
- `--hide-cursor` — скрыть курсор (по умолчанию он включён).
- `--check` — проверить захват и энкодер без очков (откроет диалог portal).
- `--bitrate-mbps 10` — безопасный default для x264; 12 тоже проходит. На 14 проверяйте `oversize_frame` в логе.

### Portal: если не работает

- `gst-launch-1.0 not found` — установите GStreamer tools (см. §1).
- `GStreamer has neither x264enc nor vaapih264enc` — установите плагины (см. §1).
- `Portal ScreenCast failed` — проверьте, что xdg-desktop-portal запущен:
  `systemctl --user status xdg-desktop-portal-gnome`.
- В Game Mode поверх gamescope portal может не показать диалог. Запускайте из Desktop Mode.

## 6. Резервный путь: kmsgrab

`kmsgrab` читает **primary DRM plane** и требует root. Он не видит hardware-cursor, поэтому курсор нужно перевести в software-режим.

```bash
# затем выйти из GNOME и войти снова (или reboot)
```

После перелогина:

```bash
sudo .venv/bin/python scripts/stream_linux.py \
    --source desktop --desktop-capture kmsgrab \
    --kmsgrab-rotate 270 --capture-fps 60 --bitrate-mbps 14
```

Проверить переменную после перелогина:

```bash
echo "$MUTTER_DEBUG_DISABLE_HW_CURSORS"   # должно быть 1
```

Почему 270: панель Steam Deck физически 800×1280, а скан в kmsgrab приходит повёрнутым. `90` разворачивает не в ту сторону.

Если zero-copy GPU-цепочка не запускается:

```bash
sudo .venv/bin/python scripts/stream_linux.py \
    --source desktop --desktop-capture kmsgrab \
    --kmsgrab-rotate 270 --gpu-filters off --bitrate-mbps 14
```

`--gpu-filters auto` (default) делает два коротких probe-а: GPU `hwmap → scale_vaapi → transpose_vaapi → pad_vaapi` и readback-путь. Если GPU-путь падает, автоматически выбирается readback. `--gpu-filters on/off` задаёт режим вручную.

## 7. Flatpak

Flatpak использует тот же portal-путь и не требует root/`kmsgrab`/FFmpeg с PipeWire.

```bash
flatpak install flathub org.gnome.Platform//49 org.gnome.Sdk//49
flatpak-builder --user --install --force-clean build-dir \
    flatpak/io.github.sevara.G2Bridge.yml
flatpak run io.github.sevara.G2Bridge
```

Если `flatpak-builder` нет:

```bash
sudo rpm-ostree install flatpak-builder
sudo systemctl reboot
```

При первом запуске появится диалог portal; выберите монитор. Курсор включён. Подробности — в `flatpak/README.md`.

## 8. Тестовая картинка, файл и граббер

```bash
# тестовая картинка
.venv/bin/python scripts/stream_linux.py --source testsrc

# проверить захват/энкодер без очков
.venv/bin/python scripts/stream_linux.py --source testsrc --check

# принудительно программный энкодер
.venv/bin/python scripts/stream_linux.py --source testsrc --encoder libx264

# файл, зациклен
.venv/bin/python scripts/stream_linux.py --source file --file ~/Videos/clip.mp4
```

Аналоговый вход / USB-граббер:

```bash
# PAL / композит 720x576@25
.venv/bin/python scripts/stream_linux.py \
    --source v4l2 --device /dev/video0 \
    --input-size 720x576 --input-fps 25 \
    --fps 60 --bitrate-mbps 10

# NTSC 720x480@30
.venv/bin/python scripts/stream_linux.py \
    --source v4l2 --device /dev/video0 \
    --input-size 720x480 --input-fps 30 \
    --fps 60 --bitrate-mbps 10
```

Картинка масштабируется с сохранением пропорций и дополняется чёрными полями до 1920×1080.

Посмотреть возможности граббера:

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video0 --list-formats-ext
```

## 9. Качество, задержка и лимиты

- Выход всегда 1920×1080, 60 fps по умолчанию. Масштабирование — bicubic; можно выбрать `--scaler lanczos` (резче, больше CPU) или `fast_bilinear` (быстрее).
- VAAPI CBR: 14 Мбит/с по умолчанию, `-max_frame_size 55000`, `-async_depth 1`, `-bf 0`, GOP 3 с, `-aud 1`.
- libx264: 16 Мбит/с по умолчанию, `tune=zerolatency`, `nal-hrd=cbr`, `-bf 0`.
- Portal x264: 10 Мбит/с по умолчанию, `vbv-buf-capacity` подбирается под битрейт, чтобы keyframe оставался ниже ~56 КБ. 12 Мбит/с тоже проверено; 14 — на границе.
- **Filler-NAL**: VAAPI CBR добивает короткие кадры NAL type 12. Скрипт ставит `-bsf:v filter_units=remove_types=12`, а AUD вставляет сам энкодер через `-aud 1`. Никакого `h264_metadata` в цепочке больше нет.
- GPU-путь kmsgrab: `hwmap=derive_device=vaapi,scale_vaapi=format=nv12,transpose_vaapi,scale_vaapi,pad_vaapi` — без readback, минимальная задержка. Если драйвер не импортирует DCC/tiled scanout, auto-режим откатится на readback.
- Кадр больше ~56 КБ может дать чёрный экран/зависание. Скрипт отбрасывает такие кадры и перезапускает энкодер; смотрите `oversize_frame` в логе.
- При 60 fps максимум по среднему битрейту ~24 Мбит/с; при 100 fps ~40 Мбит/с. Но Deck и очки могут не выдержать — начинайте с 10–14.

## 10. Логи

По умолчанию:

```text
~/.local/state/g2-bridge/logs/*.jsonl
```

При запуске через `sudo` скрипт пытается писать в домашний каталог пользователя из `SUDO_USER`. Путь можно задать явно:

```bash
--log /tmp/g2.log
```

В логе: `ready`, `streaming`, `stats`, `oversize_frame`, `encoder_restart`.

## 11. Если что-то не работает

| Симптом | Что делать |
|---|---|
| `lsusb` не показывает `2ca3:0020` | Заменить C-to-C на C→A + A→C; попробовать powered hub; проверить `dmesg -w`; открыть Virtual Flight |
| `Access denied` / `PermissionError` | udev-правило: `sudo udevadm control --reload && sudo udevadm trigger`; группа/`sudo` |
| `The goggles answered but ignored simulator mode` | На очках не открыт **More → DJI Virtual Flight** |
| Чёрный экран, зависание | Понизить `--bitrate-mbps` и/или `--fps`; передёрнуть питание очков |
| Portal не показывает диалог | Desktop Mode вместо Game Mode; `systemctl --user status xdg-desktop-portal-gnome` |
| `h264_vaapi` не работает | `--encoder libx264` (больше CPU) |
| `ffmpeg` нет | `sudo rpm-ostree install ffmpeg` + reboot (не нужен для portal) |
| `.venv` не создаётся | `uv` (см. §1) или `rpm-ostree install python3-pip` |
| Portal-кадры больше 56 КБ | `--bitrate-mbps 10`; проверьте `oversize_frame` |

## 12. Шпаргалка

```bash
cd ~/Documents/Default\ Project/g2-bridge
./setup_bazzite.sh

.venv/bin/python tools/research/probe_goggles.py --descriptors-only
.venv/bin/python tools/research/probe_goggles.py
.venv/bin/python tools/research/probe_goggles.py --test-video --seconds 20

# рабочий стол с курсором, без root
.venv/bin/python scripts/stream_linux.py --source desktop

# kmsgrab fallback, после software-cursor + relogin
sudo .venv/bin/python scripts/stream_linux.py --source desktop \
    --desktop-capture kmsgrab --kmsgrab-rotate 270 --bitrate-mbps 14

.venv/bin/python scripts/stream_linux.py --source testsrc
.venv/bin/python scripts/stream_linux.py --source v4l2 --device /dev/video0 \
    --input-size 720x576 --input-fps 25 --fps 60 --bitrate-mbps 10

flatpak run io.github.sevara.G2Bridge
```
