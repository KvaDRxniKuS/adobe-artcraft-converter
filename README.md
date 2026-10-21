# Adobe ↔ Craft Converter

**Native Windows desktop utility** with two levels of tabs: application pair, then data type. Implemented: Premiere Pro ↔ FilmCraft projects and hotkeys, and independent AE Pixel Sorter 2 / Deep Glow 2 → EffectCraft plug-in ports. Unimplemented tabs are clearly marked *planned*. The UI uses PySide6 without a browser or server; Russian/English preference is saved between launches.

> **Project-conversion status:** one desktop queue accepts Premiere `.prproj` and FilmCraft `.fcproj` projects and detects the direction from file content. FilmCraft → Premiere now builds a new project graph **without a populated Premiere reference** (or any required Premiere input). Native compatibility remains experimental: open the result in Premiere Pro to verify it.

## Features

- Native desktop UI grouped by **Premiere Pro ↔ FilmCraft**, **After Effects ↔ EffectCraft**, **Photoshop ↔ PhotoCraft**, each with **Projects / Hotkeys / Plugins** subtabs. All nine subtabs use the same scrollable, visibly framed source/destination cards, drop zone and action footer. Drop files on the zone or input field: working tabs select matching file types (projects support multiple files; hotkeys and plug-ins take one); conversion still validates their contents. Unfinished tabs accept drops **only to show selected paths** and say "Not implemented yet"; they never create output. The Premiere project page additionally keeps one mixed queue and per-project options.
- Premiere Pro `.prproj` → FilmCraft `.fcproj` conversion, including supported sequences, tracks, clips, transitions, and selected effects.
- Experimental direct FilmCraft `.fcproj` → Premiere `.prproj` conversion in the same queue, creating media, sequences, tracks and clips from FC references; an empty Premiere shell is optional.
- Premiere KYS XML ↔ FilmCraft keyboard-shortcut JSON conversion from the **Premiere Pro ↔ FilmCraft → Hotkeys** subtab or CLI.
- **Experimental:** inspect any Windows AE `.aex`, export independently implemented EffectCraft WebAssembly effects for Pixel Sorter 2 and Deep Glow 2, or produce a diagnostic report when no port exists. Never claim that an unrelated DLL was converted. No binary translation or guarantee of AE render parity.
- Conversion reports list unsupported or unmapped items instead of guessing at command/effect equivalence.
- Original project media is referenced, not copied; moved media must be relinked. A single static `graphic_text` layer per Graphic clip is encoded as an editable Premiere Type-tool title. Unsupported or more complex Graphics fall back to PNGs beside the project.

## Repository layout

- At the top level: `Start_Converter.bat`, `Build_Windows_EXE.bat`, `desktop_app.py`, `update_converter.py`, the four CLI scripts, `requirements.txt` and this README — entry points and build instructions remain visible.
- `craft_converter/`: importable conversion helpers, Premiere graph fixtures and Python-embedded EffectCraft assets (not separate commands).
- `resources/shortcuts/`: sanitized Premiere and FilmCraft shortcut templates, bundled by the Windows build and included in source-only updates.
- `effectcraft_plugins/`: EffectCraft WASM examples, manifests and AssemblyScript sources; `tools/`: effect build scripts and an optional AE-host metadata JSX (also included in source-only updates); `tests/`: automated checks.
- `uploads/`: ignored local user files and conversion outputs; do not add them to Git or move them as part of a source update.

## Windows: run from source

Requires Python 3.10+ and Windows.

```powershell
py -3 -m pip install -r requirements.txt
py -3 desktop_app.py
```

## Windows: build a standalone EXE

1. Install Python 3.10+ with the Python Launcher (`py`).
2. Run `Build_Windows_EXE.bat`.
3. The script installs PySide6, Pillow, flatbuffers and PyInstaller, builds `FilmCraftConverter.exe`, and copies it beside the source files.
4. Launch the EXE. Python and a browser are not required to run the built app.

`Start_Converter.bat` prefers a Python source launch so it can check for source updates first. If Python/PySide6 is unavailable, it falls back to an existing EXE, which **is not automatically updated**. The first EXE build needs an internet connection to install dependencies. A Windows EXE must be built on Windows; no prebuilt binary is included in this repository.

### Source auto-updates on launch

With Python 3.10+ installed, the batch file uses `update_converter.py` to inspect **all branches of this repository** and selects the branch whose HEAD has the most recent *committer date* (not necessarily `main`). It downloads that commit's source ZIP from GitHub and runs the downloaded Python app. It checks on each launch; no Git or GitHub account is required. Only download code from this repository if you trust everyone who can push to its branches.

Versions are cached under `%LOCALAPPDATA%\FilmCraftConverter\source-updates\versions\<commit>`. Your checkout, launcher, EXE, user projects, and shortcut profiles are **not overwritten**. If GitHub is offline/rate-limited or an update fails validation, the last cached version is launched (or the local source if none is cached). Set `FILMCRAFT_SKIP_UPDATE=1` before launching to run the local source without a network check. The check is limited to 40 branches because unauthenticated GitHub API requests are rate-limited; when this limit is exceeded, it falls back safely.

**One-time migration:** a checkout with the old `update_converter.py` cannot install the new nested source layout: it only extracted root files, and the source updater intentionally never replaces its own local copy. Update that checkout from the branch containing this layout change (for example with `git pull` on that branch, or a fresh source ZIP), then launch `Start_Converter.bat` again. Keep your existing `uploads/` and EXE; do not copy user files into Git.

This is a **source-only** updater: dependencies (PySide6, flatbuffers for editable titles and Pillow for raster fallback) are not installed automatically. After updating sources, run `py -3 -m pip install -r requirements.txt` if they are missing. The EXE is neither downloaded nor rebuilt automatically; to update a standalone EXE, rebuild it with `Build_Windows_EXE.bat` or publish a release binary separately.

## Project conversion: shared queue

1. Open **Premiere Pro ↔ FilmCraft → Projects**. Drag `.prproj` and/or `.fcproj` onto this page, or click **Add projects**. Premiere XML (`.xml`/`.txt`) and FilmCraft project JSON (`.json`) are also accepted when their contents match a supported project format. The **Direction** column shows PR → FC or FC → PR; shortcut profiles belong to the adjacent **Hotkeys** subtab, not this project queue.
2. **No Premiere project is required for FC → PR.** Optionally select an FC row and specify an *empty* Premiere shell from your version; only its build-version strings are used. There is no field for a populated reference. If the experimental native title is unsuitable, check **Use PNG for Graphic** on that FC row to force the raster fallback. PR → FC also needs no template.
3. Choose an output folder and click **Convert queue**. Items with an invalid optional shell path are skipped; other queued projects continue. Output extensions follow the detected direction (`.fcproj` or `.prproj`), and each project gets a sibling `*_conversion_report.md`. Existing output/report names are not replaced; a numbered name is chosen instead.
4. Read the reports and verify results in FilmCraft or Premiere Pro.

**Premiere → FilmCraft:** supported effects and transitions vary. Some effect parameters, animation/keyframes, masks, plugins, and version-specific settings may be approximated or omitted. Multistream audio routing uses Premiere's `SecondaryIndex`; FilmCraft must support the relevant multistream audio behavior.

## Keyboard shortcuts

Open **Premiere Pro ↔ FilmCraft → Hotkeys**. This inline form accepts a Premiere `.kys` XML file or FilmCraft shortcut JSON file and detects the direction from its content. The CLI equivalents are:

```powershell
py -3 shortcut_converter.py my-shortcuts.kys FilmCraft.json `
  --fc-template resources/shortcuts/FilmCraft_Shortcuts_Template.json --language en

py -3 shortcut_converter.py FilmCraft.json Premiere.kys `
  --kys-template resources/shortcuts/Premiere_Shortcuts_Template.kys --language en
```

The bundled template files are **sanitized mapping catalogs**: they contain no user's assigned key combinations. For Premiere output, commands not represented in the FilmCraft mapping may remain unassigned; for FilmCraft output, unmapped commands are reported. If multiple FilmCraft commands map to one Premiere command, only the first is written and the conflict is reported. The crosswalk is intentionally conservative and does not fuzzy-match command names. If you use a personal shortcut profile as an input, keep it private and do not commit it.

## After Effects `.aex` → EffectCraft `.wasm` (independent Pixel Sorter & Deep Glow ports)

**Ready-to-load effects:** [PixelSorter_EffectCraft.wasm](effectcraft_plugins/PixelSorter_EffectCraft.wasm) and [DeepGlow_EffectCraft.wasm](effectcraft_plugins/DeepGlow_EffectCraft.wasm). In the **EffectCraft desktop app**, choose **Effect → Load Effect Plug-in…**, select one `.wasm` and apply the effect from **Stylize** to a layer (then adjust Effect Controls). **For Deep Glow beyond the footage bounds, do not apply the effect alone:** see the companion [ApplyDeepGlowWithBounds.jsx](effectcraft_plugins/ApplyDeepGlowWithBounds.jsx) below. The browser build cannot load WASM plug-ins. Alternatively copy the file into the `Plug-ins` directory beside EffectCraft's settings and restart (see [EffectCraft plug-in documentation](https://github.com/storytold/effectcraft/blob/main/docs/plugins.md)).

Open **After Effects ↔ EffectCraft → Plugins**. Select *any* Windows AE `.aex` (or `.aex.txt` from an upload) and a new `.wasm` path. The converter checks the DLL **statically** (without running it). For identified **AE Pixel Sorter 2** or **Deep Glow 2** it writes a working **independent** EffectCraft effect and `*_conversion_report.md`; Deep Glow also produces `*_apply_with_bounds.jsx` for extending the layer before glow. For any other valid effect DLL it writes only `*_aex_analysis.md` with metadata and a reason why there is no port; **no fake `.wasm`** is created. Corrupt binaries and installers are rejected. Other After Effects data types, Premiere plug-ins and Photoshop/PhotoCraft pages remain planned. CLI (exit code 2 means inspection succeeded, but no WASM port exists):

```powershell
py -3 aex_to_effectcraft.py "C:\path\Deep Glow.aex" "C:\path\DeepGlow_effectcraft.wasm" --language en
# Or on Linux/macOS: python3 aex_to_effectcraft.py INPUT.aex OUTPUT.wasm
```

The parser bounds input to 64 MiB and accepts structurally valid x86/x64 Windows PE DLLs for analysis. It reads PE exports and, when present, the AE PiPL resource's declared **effect name, category and match name**. PiPL does not declare the renderer's blur shape, parameter bounds, UI groups, slider widgets or keyframe permissions. No installer, Adobe software, network, Node.js or build toolchain is needed to *use* the converter or load its WASM. The supplied binary is never executed, copied into the output, decompiled or used to bypass licensing. **There is no generic way to turn arbitrary proprietary After Effects machine code into working EffectCraft WebAssembly**: lifting a name check can allow inspection, but a faithful effect needs source code or a separate reimplementation. Unknown plug-ins produce diagnostics, not a fake effect; please provide the `.aex`, controls and paired AE before/after frames when requesting one.

**Optional AE-host parameter inventory:** in After Effects, select a composition and one layer containing the effect, then run [`tools/export_ae_effect_metadata.jsx`](tools/export_ae_effect_metadata.jsx) from **File → Scripts → Run Script File…**. Choose the effect and save its JSON profile. In the converter's Plugins tab select this optional profile, or pass `--ae-profile path/to/profile.json` to the CLI above. The report includes observed group names, numeric min/max flags, keyframe and expression capability, and compares its match name with the DLL's PiPL. **No values, media or project paths** are exported; still review the JSON before sharing. AE's scripting API does **not** expose custom curve editors, slider-versus-number widgets or the render algorithm reliably; these remain unknown. The JSX requires After Effects and has not been exercised here. A profile informs the report; it cannot make an unsupported effect render in EffectCraft.

**Opt-in Deep Glow values:** the `.aex`/PiPL does **not** contain readable original defaults. To avoid manually copying settings, in installed After Effects add a **fresh** Deep Glow effect (for factory defaults), or select the already adjusted effect (for your current comparison settings). With that layer selected run [`tools/export_ae_deep_glow_values.jsx`](tools/export_ae_deep_glow_values.jsx) via **File → Scripts → Run Script File…**, choose the PEDG effect and review the JSON. In the Plugins tab select it in the **separate numeric settings snapshot** field, or pass `--ae-values snapshot.json` to the CLI. Only **Radius, Exposure, Threshold, Threshold Smooth, Spread and Source Opacity** are mapped by exact name and copied into the embedded manifest's defaults for **new** EffectCraft effect instances; ambiguous, out-of-range or differently ordered controls (e.g. Tint Mix and Blend Mode) remain unchanged and are reported. No other values, media paths or colours are exported. Numbers are copied as-is: shared units and visual parity have **not** been measured. With no snapshot, our own defaults remain, not AE's. The profile above remains value-free and independent; no After Effects installation is needed for conversion itself. The snapshot JSX has only been tested in a simulated host, not installed AE.

**Halo outside footage (Deep Glow 0.4.0):** EffectCraft plug-in API v1 passes an in-place source-sized buffer; the `.wasm` cannot grow its bounds, so applying it alone still cuts off light at the footage edge. After **loading** the `.wasm`, select the footage layer(s) in EffectCraft desktop and run the generated `*_apply_with_bounds.jsx` from **File → Scripts → Run Script File…** (or use the ready [example](effectcraft_plugins/ApplyDeepGlowWithBounds.jsx)). The script applies EffectCraft's **Utility → Grow Bounds before Deep Glow**, with its Pixels property expression linked to Radius, including keyframes. Keep this order and the renamed glow effect name. Alternatively add Grow Bounds manually *before* the plug-in, setting Pixels generously enough for the chosen radius. For very large footage/radii, the host's 4000 px padding range and our 9-million-pixel WASM render limit may still cut off glow; use smaller footage/a suitable comp-sized precomp or update EffectCraft itself. The JSX was tested in a mock script host, and padded-frame WASM rendering in Node.js, **not in EffectCraft's desktop UI**. This is a bounded workaround, not a host or AE algorithm fix.

EffectCraft WASM plug-in API v1 accepts a flat list of standard parameters (no nested UI groups or custom curve widgets); ordinary parameters can be keyframed. Sliders must declare finite hard min/max, but can use separate `sliderMin`/`sliderMax` for a convenient soft range. The Pixel Sorter port has 18 independently defined controls. The Deep Glow-like port has 14 controls including threshold, radius, exposure, multi-scale spread, tint and alpha expansion. Version **0.2.0** replaced the old square box blur with a small-radius Gaussian and a fast three-box Gaussian approximation for larger radii. Version **0.3.0** also removes the artificial 256 px hard stop on Radius: the slider still runs 0–256 for convenient adjustment, while its number field accepts up to our chosen 1e9 limit (EffectCraft v1 requires some finite hard maximum). Rendering caps the *effective* radius at 16 times the longest frame dimension to avoid overflow and wasted work; beyond that, larger numbers produce the same image. This is a property of our port, not a limit recovered from the `.aex`, and **this is not AE Deep Glow's algorithm**. Version **0.4.0** adds opt-in AE numeric default transfer and a companion Grow Bounds script; the blur implementation is unchanged and WASM alone still cannot extend the frame. Neither effect matches the original automatically; AE presets, external inputs, GPU options and licensing are not transferred. A user confirmed that the previous Deep Glow version loaded and produced glow in EffectCraft; this version's binary/snapshot and scripted bounds workaround have only been tested in Node.js and Wasmtime / a script-host mock here. A matched AE/EffectCraft frame pair is needed to assess visual parity.

**Updating an existing Deep Glow plug-in:** exit EffectCraft first. It rejects a second plug-in with the same effect id in one session. Replace the old `.wasm` in your auto-load folder (if present), keeping only one copy, restart EffectCraft, then load the new `.wasm` with **Effect → Load Effect Plug-in…** if necessary. The source converter exports this updated binary; it does not replace an already exported file automatically.

Standalone AssemblyScript sources and manifests live in `effectcraft_plugins/`; the self-contained Python assets `craft_converter/effectcraft_pixel_sorter.py` and `craft_converter/effectcraft_deep_glow.py` allow source-only updates and Windows EXEs without bundling a compiler. To **rebuild sources** (not needed for users): `npm install --prefix .venv/wasm-tools --no-save assemblyscript@0.28.20`, then run `python3 tools/build_pixel_sorter.py --asc .venv/wasm-tools/node_modules/.bin/asc` or `python3 tools/build_deep_glow.py --asc .venv/wasm-tools/node_modules/.bin/asc` (Windows: `asc.cmd`). Verify with `node tests/effectcraft_wasm_smoke.cjs`, `node tests/deep_glow_wasm_smoke.cjs` and Python tests.

## FilmCraft → Premiere limitations (experimental)

The writer constructs a native-style **media → master clip → sequence → track → clip** reference graph from FC items, assigning fresh Premiere object IDs. It handles multiple sequences, tracks, reused media, basic video/audio timings and sequences nested by unambiguous name. Original media are **linked by path, never copied**. For a Graphic clip with **one static, supported `graphic_text` layer**, it embeds the Unicode text, font name, size, fill/stroke, alignment and basic transforms in a Premiere Type-tool `AE.ADBE Text` component with a binary Source Text payload. This makes the title *intended to be editable*, instead of rendering it to an image. Fonts must be installed on the Premiere computer; their metrics and layout may differ. Animated or multi-layer titles and unsupported styles fall back to a separate PNG beside the `.prproj` (requires Pillow); keep any generated PNGs with the project. A missing flatbuffers library also triggers PNG fallback; install all dependencies with `py -3 -m pip install -r requirements.txt`. Both small, neutral graph layouts originate in public MIT fixtures (attribution and licenses in `craft_converter/premiere_seed.py` and `craft_converter/premiere_text_seed.py`), not a project containing your media. An optional empty shell only supplies two build-version strings; it is **not** a guarantee that the graph matches your Premiere version. **The native title has passed structural/payload and timeline round-trip tests, not an Adobe Premiere open, edit or render test.** Diagnostics in the report are currently in Russian even in the English UI.

The CLI uses the same direct writer:

```powershell
py -3 fcproj_to_prproj.py project.fcproj output.prproj
# Optionally supply version metadata:
py -3 fcproj_to_prproj.py project.fcproj output.prproj --shell empty-premiere-shell.prproj
# Force PNG instead of the experimental editable title:
py -3 fcproj_to_prproj.py project.fcproj output.prproj --graphics png
```

This remains **experimental**. The embedded graph is a structural starting point, not a verified Premiere export for every version. Apart from the static `graphic_text` subset and its PNG fallback, the converter currently does not reverse-map most effects, transitions, retiming, and several audio/track/sequence properties; omissions are reported. It resolves clip references by `project.items` key or an unambiguous item `id`. If a referenced item is truly absent from `project.items`, it cannot reconstruct that clip from its numeric ID alone and reports the clip name/ID. It rejects missing references, overlapping clips on one track and cyclic nesting rather than silently creating an inconsistent project; other unsupported properties are reported as omissions. Round-trip XML/reference tests **do not prove Premiere Pro opens or renders the output**. Keep original projects, read the report and check results in your Premiere version before relying on them.

## Development checks

```powershell
py -3 -m compileall -q desktop_app.py update_converter.py aex_to_effectcraft.py fcproj_to_prproj.py prproj_to_fcproj.py shortcut_converter.py craft_converter
py -3 -m unittest discover -s tests -v
```

The PySide6 GUI should also be smoke-tested on Windows with real FilmCraft/Premiere projects. Headless UI tests are skipped when system Qt libraries are unavailable (as in the development sandbox); this is not a Windows build or Premiere compatibility test.

## Repository hygiene and privacy

- User projects, AE settings snapshots, test outputs, shortcut profiles, generated `.wasm`/`.jsx` files and conversion reports belong in `uploads/` or another local folder; do not commit them. The small ready-to-load [Pixel Sorter](effectcraft_plugins/PixelSorter_EffectCraft.wasm), [Deep Glow](effectcraft_plugins/DeepGlow_EffectCraft.wasm) and its generic [bounds helper](effectcraft_plugins/ApplyDeepGlowWithBounds.jsx) are exceptions. The original `.aex` and installer must not be added to the repository.
- The committed shortcut templates are blank/sanitized catalogs. Do not replace them with personal profiles before publishing. The embedded Premiere graph layouts are adapted from MIT-licensed public fixtures; sources, changes and full license notices are in `craft_converter/premiere_seed.py` and `craft_converter/premiere_text_seed.py`.
- No credentials or user project/media paths are intended to be part of the source release. Run a final repository scan before pushing, especially after adding test fixtures.
- No `LICENSE` file is included. Choose a license before describing the project as open source; without one, normal copyright restrictions apply.

---

# Конвертер Adobe ↔ Craft (Русский)

**Нативная настольная утилита для Windows** с двумя уровнями вкладок: пара программ → тип данных. Работают проекты и горячие клавиши Premiere Pro ↔ FilmCraft, а также независимые порты AE Pixel Sorter 2 и Deep Glow 2 → EffectCraft. Остальные направления отмечены «Пока не реализовано». Интерфейс на PySide6, без браузера и веб-сервера. Выбранный русский/английский язык запоминается.

> **Состояние конвертации проектов:** одна очередь принимает Premiere `.prproj` и FilmCraft `.fcproj` и определяет направление по содержимому файла. FilmCraft → Premiere теперь строит новый граф проекта **без заполненного эталона** и без обязательного проекта Premiere. Совместимость с Premiere остаётся экспериментальной: результат нужно открыть и проверить в программе.

## Возможности

- Нативный интерфейс с группами **Premiere Pro ↔ FilmCraft**, **After Effects ↔ EffectCraft**, **Photoshop ↔ PhotoCraft** и подвкладками **Проекты / Горячие клавиши / Плагины**. Все девять подвкладок имеют одинаково оформленные блоки источника/результата, зону перетаскивания и нижнюю строку действий. На рабочих вкладках файл можно перетащить в зону или поле источника (проекты принимают несколько файлов, горячие клавиши и плагины — по одному); при конвертации содержимое проверяется отдельно. Неготовые разделы позволяют **только показать выбранные пути**, явно сообщают «Пока не реализовано» и не создают файлы. В проектах Premiere/FilmCraft сохраняются общая очередь и параметры каждого проекта.
- Конвертация `.prproj` → `.fcproj` с поддержкой части последовательностей, дорожек, клипов, переходов и эффектов.
- Экспериментальная прямая конвертация FilmCraft `.fcproj` → Premiere `.prproj` в той же очереди: медиа, последовательности, дорожки и клипы создаются из ссылок FC; пустая оболочка Premiere необязательна.
- Конвертация Premiere KYS XML ↔ FilmCraft JSON через вкладку **Premiere Pro ↔ FilmCraft → Горячие клавиши** или CLI.
- **Экспериментально:** статический анализ любого Windows AE `.aex`; для Pixel Sorter 2 и Deep Glow 2 создаются самостоятельные работающие WASM-эффекты EffectCraft, для других — диагностика без ложного WASM. Это **не** перевод закрытого бинарного кода и не гарантия совпадения с AE.
- Отчёты перечисляют неподдерживаемые и несопоставленные элементы; конвертер не угадывает похожие команды.
- Исходные медиа не копируются. Один простой статичный слой `graphic_text` на клипе Graphic кодируется как редактируемый титр Premiere; сложные случаи сохраняются в PNG. Перемещённые файлы нужно перепривязать в целевой программе.

## Структура репозитория

- В корне — `Start_Converter.bat`, `Build_Windows_EXE.bat`, `desktop_app.py`, `update_converter.py`, четыре CLI-скрипта, `requirements.txt` и README: запуск и сборка остаются на виду.
- `craft_converter/` — вспомогательные модули, каркасы графа Premiere и встроенные Python-ресурсы EffectCraft; это не отдельные команды.
- `resources/shortcuts/` — обезличенные шаблоны горячих клавиш, которые включаются в EXE и автообновления исходников.
- `effectcraft_plugins/` — готовые WASM, манифесты и исходники AssemblyScript; `tools/` — сборка эффектов и необязательный JSX для анализа в AE (входит в обновления исходников); `tests/` — проверки.
- `uploads/` — исключённые из Git пользовательские файлы и результаты: обновление исходников их не перемещает.

## Запуск из исходников в Windows

Нужны Python 3.10+ и Windows.

```powershell
py -3 -m pip install -r requirements.txt
py -3 desktop_app.py
```

## Сборка EXE в Windows

1. Установите Python 3.10+ с Python Launcher (`py`).
2. Запустите `Build_Windows_EXE.bat`.
3. Скрипт установит PySide6, Pillow, flatbuffers и PyInstaller, соберёт `FilmCraftConverter.exe` и скопирует его рядом с исходниками.
4. Запустите EXE. Для уже собранного приложения Python и браузер не нужны.

`Start_Converter.bat` предпочитает запуск исходников через Python, чтобы сначала проверить обновления. Если Python/PySide6 недоступен, запускается имеющийся EXE, но **он автоматически не обновляется**. Для первой сборки EXE нужен интернет для установки зависимостей. EXE нужно собирать на Windows; готового бинарника в репозитории нет.

### Автообновление исходников при запуске

При наличии Python 3.10+ батник вызывает `update_converter.py`: проверяет **все ветки этого репозитория** и выбирает ту, у которой самый поздний *коммит по дате коммиттера* (это не обязательно `main`). Затем скачивает ZIP исходников именно этого коммита с GitHub и запускает обновлённый код. Проверка проводится при каждом запуске; Git и аккаунт GitHub не нужны. Используйте такой режим, только если доверяете всем, кто может публиковать ветки в репозитории.

Версии сохраняются в `%LOCALAPPDATA%\FilmCraftConverter\source-updates\versions\<commit>`. Исходная папка, батник, EXE, пользовательские проекты и профили клавиш **не перезаписываются**. Если GitHub недоступен, исчерпан лимит API или обновление повреждено, запускается последняя сохранённая версия (либо локальные исходники). Чтобы запустить локальную версию без проверки сети, задайте `FILMCRAFT_SKIP_UPDATE=1`. Из-за лимита GitHub API без авторизации проверяются репозитории не более чем с 40 ветками; при превышении лимита используется резервная версия.

**Однократный переход:** прежний `update_converter.py` извлекал только файлы из корня и не может установить новую вложенную структуру; автообновление не заменяет его локальную копию. Один раз обновите исходную папку из ветки с этой реорганизацией (`git pull` в этой ветке или новый ZIP исходников), затем снова запустите `Start_Converter.bat`. Сохраните свои `uploads/` и EXE, не переносите пользовательские файлы в Git.

Это обновление **только исходников**: зависимости (PySide6, flatbuffers для редактируемых титров и Pillow для PNG) автоматически не устанавливаются. После обновления исходников при необходимости выполните `py -3 -m pip install -r requirements.txt`. Готовый EXE не скачивается и не пересобирается автоматически; для него повторно запустите `Build_Windows_EXE.bat` или публикуйте отдельный бинарный релиз.

## Конвертация проектов: общая очередь

1. Откройте **Premiere Pro ↔ FilmCraft → Проекты**. Перетащите `.prproj` и/или `.fcproj` на эту страницу либо нажмите **Добавить проекты**. Premiere XML (`.xml`/`.txt`) и JSON проекта FilmCraft (`.json`) тоже принимаются, если содержимое соответствует формату проекта. Столбец **Направление** показывает PR → FC или FC → PR; профили горячих клавиш — на соседней вкладке, а не в очереди проектов.
2. **Для FC → PR проект Premiere не нужен.** При желании выделите FC-строку и укажите *пустую* оболочку своей версии Premiere: из неё берутся только строки версии сборки. Поля для заполненного эталона больше нет. Если экспериментальный титр не подходит, включите **Использовать PNG для Graphic** на этой FC-строке. Для PR → FC шаблоны также не нужны.
3. Выберите папку вывода и нажмите **Конвертировать очередь**. Только FC-строки с некорректным путём к необязательной оболочке пропускаются; остальные продолжают обработку. Формат результата (`.fcproj` или `.prproj`) определяется автоматически; рядом создаётся `*_conversion_report.md`. Существующие проекты и отчёты не перезаписываются — выбирается имя с номером.
4. Прочитайте отчёты и проверьте результаты в FilmCraft или Premiere Pro.

**Premiere → FilmCraft:** поддержка эффектов и переходов ограничена: отдельные параметры, ключевые кадры/анимация, маски, плагины и настройки версий могут переноситься приближённо или пропускаться. Маршрутизация многопоточного аудио использует Premiere `SecondaryIndex`; FilmCraft должен поддерживать соответствующее поведение.

## Горячие клавиши

Вкладка **Premiere Pro ↔ FilmCraft → Горячие клавиши** принимает Premiere `.kys` (XML) или FilmCraft JSON и определяет направление по содержимому. Примеры команд CLI приведены в английской части README; замените `--language en` на `--language ru`, если нужен русский отчёт.

Включённые шаблоны — **очищенные каталоги соответствий** без пользовательских назначений. В выходном KYS команды, не покрытые таблицей FilmCraft, могут остаться без клавиш; неподдерживаемые команды указываются в отчёте. Если несколько FilmCraft-команд сопоставились одной команде Premiere, переносится первая, а конфликт попадает в отчёт. Сопоставление намеренно консервативное. Не добавляйте личные профили горячих клавиш в публичный репозиторий.

## After Effects `.aex` → EffectCraft `.wasm` (Pixel Sorter и Deep Glow)

**Готовые независимые эффекты:** [PixelSorter_EffectCraft.wasm](effectcraft_plugins/PixelSorter_EffectCraft.wasm) и [DeepGlow_EffectCraft.wasm](effectcraft_plugins/DeepGlow_EffectCraft.wasm). В **настольном EffectCraft** откройте **Effect → Load Effect Plug-in…**, выберите `.wasm`, затем примените эффект из категории **Stylize** к слою и настройте параметры в Effect Controls. **Для Deep Glow за пределами футажа одного плагина недостаточно:** используйте [ApplyDeepGlowWithBounds.jsx](effectcraft_plugins/ApplyDeepGlowWithBounds.jsx), см. ниже. Веб-версия WASM-плагины не загружает. Файл можно также поместить в папку `Plug-ins` рядом с настройками EffectCraft и перезапустить приложение ([документация](https://github.com/storytold/effectcraft/blob/main/docs/plugins.md)).

Откройте **After Effects ↔ EffectCraft → Плагины**, выберите *любой* Windows `.aex` (допускается `.aex.txt`) и новый путь `.wasm`. Программа статически анализирует DLL **без его запуска**. Для распознанных **AE Pixel Sorter 2** или **Deep Glow 2** создаётся **самостоятельная** работающая реализация эффекта и `*_conversion_report.md`; для Deep Glow также создаётся `*_apply_with_bounds.jsx`, расширяющий границы перед эффектом. Для другого корректного эффекта сохраняется только `*_aex_analysis.md` с диагностикой — **никакого подложного `.wasm`**. Повреждённый файл или установщик отклоняется. Прочие вкладки Adobe/Craft пока заглушки. CLI (код возврата 2: анализ выполнен, реализации эффекта ещё нет):

```powershell
py -3 aex_to_effectcraft.py "C:\path\Deep Glow.aex" "C:\path\DeepGlow_effectcraft.wasm"
# Linux/macOS: python3 aex_to_effectcraft.py INPUT.aex OUTPUT.wasm
```

Статический анализ принимает структурно корректные Windows PE DLL x86/x64 размером до 64 МБ и читает экспорт PE и ресурс AE PiPL (если он есть): **имя эффекта, категорию и match name**. PiPL не описывает форму размытия, пределы параметров, группы, ползунки и доступность ключевых кадров. Для работы конвертера не нужны установщик, Adobe, npm и сеть; `.aex` не исполняется, не копируется в WASM и не используется для обхода лицензии. **Универсального перевода произвольного машинного кода AE в WebAssembly EffectCraft нет**: для неизвестного эффекта нужны исходники либо отдельная реализация. Неизвестный плагин получает отчёт, а не поддельный WASM. Для следующего порта пригодятся `.aex`, настройки и одинаковые кадры «до/после» из AE.

**Дополнительная инвентаризация параметров через AE:** в After Effects выделите композицию и один слой с эффектом, затем запустите [`tools/export_ae_effect_metadata.jsx`](tools/export_ae_effect_metadata.jsx) через **File → Scripts → Run Script File…**. Выберите эффект и сохраните профиль JSON. В форме «Плагины» укажите его в необязательном поле или передайте CLI `--ae-profile путь/к/профилю.json`. Отчёт перечислит подтверждённые в AE группы, наличие и значения границ, доступность ключевых кадров и выражений; match name сверяется с PiPL. **Значения параметров и пути к медиа/проекту не выгружаются**, но всё равно просмотрите JSON перед отправкой. AE scripting API не раскрывает надёжно виджет «ползунок или поле», редактор пользовательской кривой и алгоритм рендера — эти поля остаются неизвестными. JSX требует установленный After Effects; здесь его выполнить не удалось. Профиль дополняет отчёт, но не превращает неизвестный `.aex` в работающий WASM.

**Перенос чисел Deep Glow по запросу:** `.aex`/PiPL не даёт достоверных исходных значений. Чтобы не копировать настройки вручную, в установленном After Effects добавьте **новый** Deep Glow (для заводских значений) либо выберите уже настроенный экземпляр (для сравнения его текущих значений). На слое с ним запустите [`tools/export_ae_deep_glow_values.jsx`](tools/export_ae_deep_glow_values.jsx) через **File → Scripts → Run Script File…**, выберите эффект PEDG и проверьте сохранённый JSON. Во вкладке «Плагины» укажите файл в **отдельном поле снимка чисел** либо передайте CLI `--ae-values снимок.json`. По точным именам переносятся только **Radius, Exposure, Threshold, Threshold Smooth, Spread, Source Opacity** в начальные значения **новых** экземпляров EffectCraft; неоднозначные, выходящие за пределы порта и отличающиеся по смыслу параметры (например, Tint Mix, Blend Mode) не переносятся и отмечаются в отчёте. Скрипт экспортирует лишь числовые параметры, имена и группы — не кадры, пути медиа или цветовые массивы. Числа копируются без изменений: совпадение единиц измерения и картинки **не подтверждено**. Без снимка остаются значения нашего порта, а не AE. Профиль метаданных выше по-прежнему не содержит значений. JSX проверен в симуляции API, не в установленном AE.

**Ореол за пределами исходника (Deep Glow 0.4.0):** WASM API v1 EffectCraft обрабатывает буфер на месте и **не может расширить границы сам**. С одним только `.wasm` ореол на границе футажа обрезается. Сначала **загрузите** плагин в настольный EffectCraft, выберите слой(и) футажа, затем запустите созданный конвертером `*_apply_with_bounds.jsx` через **File → Scripts → Run Script File…** (для готового эффекта — [пример](effectcraft_plugins/ApplyDeepGlowWithBounds.jsx)). Скрипт добавляет **Utility → Grow Bounds перед Deep Glow**; Pixels привязан выражением к Radius, в том числе при ключевых кадрах. Не меняйте порядок и имя переименованного скриптом эффекта. Либо добавьте Grow Bounds вручную *до* плагина и задайте запас в пикселях под текущий радиус. При больших футажах/радиусах действуют ограничения Grow Bounds (4000 пикселей) и самого порта (9 млн пикселей на кадр): может понадобиться меньший исходник/подходящая прекомпозиция размером с композицию либо изменение хоста EffectCraft. JSX проверен в симуляции, а WASM — на дополненном прозрачным полем буфере в Node.js; **в реальном интерфейсе EffectCraft не проверен**. Это ограниченный обход, а не изменение API или точная копия алгоритма AE.

API v1 WASM-плагинов EffectCraft принимает плоский список стандартных параметров: нет декларативных вложенных групп и собственных редакторов кривых, но обычные параметры поддерживают ключевые кадры. У slider обязательны конечные min/max; `sliderMin`/`sliderMax` задают отдельный удобный диапазон. Pixel Sorter использует 18 собственных параметров. Независимый аналог Deep Glow — 14 параметров: радиус, экспозиция, порог, многомасштабное свечение, окраска и расширение альфа-канала. В версии **0.2.0** прежнее квадратное размытие заменено гауссовым на малых радиусах и плавным приближением тремя проходами на больших. Версия **0.3.0** убирает искусственный жёсткий предел Radius = 256: ползунок остаётся 0–256 для удобства, а в числовое поле можно ввести больше (до выбранной нами границы 1e9: API v1 требует конечного максимума). Во время рендера эффективный радиус ограничен 16-кратной длинной стороной кадра для защиты от переполнения и лишней работы; выше этого значения изображение уже не меняется. Это настройка **нашего порта**, а не автоматически извлечённое свойство `.aex`, и **это не оригинальный алгоритм AE Deep Glow**. Версия **0.4.0** добавляет добровольный перенос чисел из AE и скрипт Grow Bounds; реализация размытия не менялась, WASM сам границы не расширяет. Совпадение с оригиналом не подтверждено: пресеты, внешние входы, GPU-возможности и лицензия не переносятся. Пользователь проверил свечение прежней версии в EffectCraft; текущий бинарник, значения и скрипт расширения проверены лишь в Node.js, Wasmtime и симуляции сценарного API. Для оценки сходства нужны одинаковые кадры и настройки в AE и EffectCraft.

**Замена уже загруженного Deep Glow:** полностью закройте EffectCraft. В одной сессии нельзя повторно загрузить плагин с тем же ID. Если файл находится в папке автозагрузки, замените старый `.wasm` новым, оставив только один экземпляр; перезапустите программу и при необходимости выберите **Effect → Load Effect Plug-in…**. Конвертер выдаёт обновлённый WASM, но ранее сохранённые результаты автоматически не перезаписывает.

Исходники AssemblyScript, манифесты и готовые WASM лежат в `effectcraft_plugins/`; `craft_converter/effectcraft_pixel_sorter.py` и `craft_converter/effectcraft_deep_glow.py` встраивают их в Python/EXE для обновлений исходников без компилятора. Для **пересборки** (пользователю не требуется): `npm install --prefix .venv/wasm-tools --no-save assemblyscript@0.28.20`, затем `python3 tools/build_pixel_sorter.py --asc .venv/wasm-tools/node_modules/.bin/asc` или `python3 tools/build_deep_glow.py --asc .venv/wasm-tools/node_modules/.bin/asc` (Windows: `asc.cmd`). Проверки: `node tests/effectcraft_wasm_smoke.cjs`, `node tests/deep_glow_wasm_smoke.cjs` и Python-тесты.

## Ограничения FilmCraft → Premiere (экспериментально)

Writer строит нативный граф ссылок **медиа → master clip → последовательность → дорожка → клип** по данным FC и назначает новые идентификаторы объектов Premiere. Поддержаны несколько последовательностей и дорожек, повторное использование медиа, базовые тайминги видео/аудио и вложенные последовательности с однозначным именем. Исходные медиа **не копируются**, а указываются путями из FC. Для клипа Graphic с **одним простым статичным слоем `graphic_text`** в компонент `AE.ADBE Text` записываются текст Unicode, имя шрифта, размер, заливка/обводка, выравнивание и базовые параметры положения: титр *предполагается редактируемым* в Premiere, а не отрисованным в картинку. Шрифт должен быть установлен на компьютере с Premiere; метрики и вёрстка могут отличаться. При нескольких слоях, анимации или неподдерживаемом стиле остаётся отдельный PNG рядом с `.prproj` (нужен Pillow); переносите PNG вместе с проектом. Если не установлен flatbuffers, также используется PNG. Установите зависимости: `py -3 -m pip install -r requirements.txt`. Оба небольших обезличенных каркаса адаптированы из публичных MIT-образцов (атрибуция в `craft_converter/premiere_seed.py` и `craft_converter/premiere_text_seed.py`); проекта Premiere с вашими медиа в них нет. Необязательная пустая оболочка даёт лишь две строки версии сборки и **не гарантирует** совместимость с вашей версией Premiere. **Нативный титр прошёл структурные тесты, проверку бинарных данных и таймлайна, но не проверку открытия, редактирования или рендера в Adobe Premiere.** Диагностика writer в отчёте пока на русском языке.

CLI использует тот же прямой writer:

```powershell
py -3 fcproj_to_prproj.py project.fcproj output.prproj
# При желании используйте строки версии из пустой оболочки:
py -3 fcproj_to_prproj.py project.fcproj output.prproj --shell empty-premiere-shell.prproj
# Для принудительного PNG вместо экспериментального редактируемого титра:
py -3 fcproj_to_prproj.py project.fcproj output.prproj --graphics png
```

Это всё ещё **экспериментальный**, а не универсальный обратный конвертер. Помимо простого статичного `graphic_text` и его PNG fallback, большинство эффектов, переходы, изменение скорости и ряд свойств аудио/дорожек/последовательностей пока не переносятся — пропуски отмечаются в отчёте. Ссылки на клипы ищутся по ключу `project.items` или по однозначному полю `id`. Если элемент действительно отсутствует в `project.items`, восстановить исходник по одному числовому ID нельзя: ошибка укажет имя клипа и ID. Отсутствующие ссылки, перекрывающиеся клипы на одной дорожке и циклические вложения отклоняются с ошибкой. Проверка XML и ссылок в тестах **не доказывает**, что Premiere Pro откроет или воспроизведёт файл. Сохраняйте оригиналы, читайте отчёт и проверяйте результат в своей версии Premiere.

## Проверки разработки

```powershell
py -3 -m compileall -q desktop_app.py update_converter.py aex_to_effectcraft.py fcproj_to_prproj.py prproj_to_fcproj.py shortcut_converter.py craft_converter
py -3 -m unittest discover -s tests -v
```

GUI также нужно проверить на Windows с реальными проектами FilmCraft/Premiere. Если системных библиотек Qt нет, headless UI-тесты пропускаются (как в среде разработки); это не проверка Windows-сборки и совместимости с Premiere.

## Чистота репозитория и приватность

- Пользовательские проекты, снимки параметров AE, результаты, профили горячих клавиш, сгенерированные `.wasm`/`.jsx` и отчёты храните локально в `uploads/` или другой папке; не коммитьте. Исключения — готовые [Pixel Sorter](effectcraft_plugins/PixelSorter_EffectCraft.wasm), [Deep Glow](effectcraft_plugins/DeepGlow_EffectCraft.wasm) и общий [скрипт границ](effectcraft_plugins/ApplyDeepGlowWithBounds.jsx). Оригинальные `.aex` и установщик не добавляйте в репозиторий.
- Шаблоны горячих клавиш очищены. Обезличенные каркасы Premiere адаптированы из публичных MIT-fixtures; источники, изменения и тексты лицензий указаны в `craft_converter/premiere_seed.py` и `craft_converter/premiere_text_seed.py`. Перед публикацией проверьте `git status` и добавляемые файлы.
- В исходниках не предполагаются токены, пользовательские пути или медиафайлы; перед push всё равно выполните финальную проверку.
- Файла `LICENSE` нет. Выберите лицензию до заявления, что проект распространяется как open source; без лицензии действуют обычные ограничения авторского права.
