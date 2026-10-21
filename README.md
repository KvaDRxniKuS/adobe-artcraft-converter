# Adobe ↔ Craft Converter

**Native Windows desktop utility** with two levels of tabs: application pair, then data type. Implemented: Premiere Pro ↔ FilmCraft projects and hotkeys, and an independent AE Pixel Sorter 2 → EffectCraft plug-in port. Unimplemented tabs are clearly marked *planned*. The UI uses PySide6 without a browser or server; Russian/English preference is saved between launches.

> **Project-conversion status:** one desktop queue accepts Premiere `.prproj` and FilmCraft `.fcproj` projects and detects the direction from file content. FilmCraft → Premiere now builds a new project graph **without a populated Premiere reference** (or any required Premiere input). Native compatibility remains experimental: open the result in Premiere Pro to verify it.

## Features

- Native desktop UI grouped by **Premiere Pro ↔ FilmCraft**, **After Effects ↔ EffectCraft**, **Photoshop ↔ PhotoCraft**, each with **Projects / Hotkeys / Plugins** subtabs; unfinished tabs show a "Not implemented yet" placeholder and tooltip. All subtabs share the same scrollable page layout (heading, source card, destination card and action footer); the Premiere project page additionally keeps one mixed drag-and-drop queue and per-project options.
- Premiere Pro `.prproj` → FilmCraft `.fcproj` conversion, including supported sequences, tracks, clips, transitions, and selected effects.
- Experimental direct FilmCraft `.fcproj` → Premiere `.prproj` conversion in the same queue, creating media, sequences, tracks and clips from FC references; an empty Premiere shell is optional.
- Premiere KYS XML ↔ FilmCraft keyboard-shortcut JSON conversion from the **Premiere Pro ↔ FilmCraft → Hotkeys** subtab or CLI.
- **Experimental:** recognize AE Pixel Sorter 2 `.aex` and export an independently implemented, working EffectCraft WebAssembly pixel-sorting effect; **not** a binary translation or a promise of pixel-for-pixel AE parity.
- Conversion reports list unsupported or unmapped items instead of guessing at command/effect equivalence.
- Original project media is referenced, not copied; moved media must be relinked. A single static `graphic_text` layer per Graphic clip is encoded as an editable Premiere Type-tool title. Unsupported or more complex Graphics fall back to PNGs beside the project.

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
  --fc-template FilmCraft_Shortcuts_Template.json --language en

py -3 shortcut_converter.py FilmCraft.json Premiere.kys `
  --kys-template Premiere_Shortcuts_Template.kys --language en
```

The bundled template files are **sanitized mapping catalogs**: they contain no user's assigned key combinations. For Premiere output, commands not represented in the FilmCraft mapping may remain unassigned; for FilmCraft output, unmapped commands are reported. If multiple FilmCraft commands map to one Premiere command, only the first is written and the conflict is reported. The crosswalk is intentionally conservative and does not fuzzy-match command names. If you use a personal shortcut profile as an input, keep it private and do not commit it.

## After Effects `.aex` → EffectCraft `.wasm` (Pixel Sorter only)

**Ready-to-load effect:** [PixelSorter_EffectCraft.wasm](effectcraft_plugins/PixelSorter_EffectCraft.wasm) (EffectCraft desktop/CLI plug-in API v1, `org.artcraft_converter.pixel_sorter`). In EffectCraft choose **Effect → Load Effect Plug-in…**, select this `.wasm`, then look under **Stylize**. The EffectCraft web app does not load WASM plug-ins. You can also put the file in the `Plug-ins` folder next to EffectCraft settings for startup loading (see [EffectCraft's plug-in docs](https://github.com/storytold/effectcraft/blob/main/docs/plugins.md)).

Open **After Effects ↔ EffectCraft → Plugins**. This is an inline form, separate from the Premiere/FilmCraft *shared project queue*. Choose an **AE Pixel Sorter 2** `.aex` (or the uploaded `.aex.txt`) and a **new** `.wasm` destination. After Effects projects/hotkeys, Premiere plug-ins and all Photoshop/PhotoCraft subtabs are placeholders, not converters. The CLI does the same plug-in conversion without PySide6:

```powershell
py -3 aex_to_effectcraft.py "C:\path\AEPixelSorter2.aex" "C:\path\PixelSorter_effectcraft.wasm" --language en
# Or on Linux/macOS: python3 aex_to_effectcraft.py INPUT.aex OUTPUT.wasm
```

The tool reads at most 64 MiB of the input, statically checks the x64 PE DLL and its exports/identifying control labels, and writes the self-contained `.wasm` plus `*_conversion_report.md` **without overwriting existing files**. No installer, After Effects installation, npm or network access is needed at conversion/use time. The `.aex` is never run, copied into the output, or decompiled into it. Unsupported `.aex` files are **rejected** rather than falsely converted; only this identified family has an independently written port. We do not transfer AE project presets, source-layer inputs, Resolution/Zoom, a license, or the original proprietary algorithm. The 18 controls (trigger/sort metrics, angle, threshold, highlights/shadows, block size, length, offset, blur, feather, seed, diagnostic output and alpha) have **our own semantics** and may differ from the Adobe plug-in. For another plug-in, supply its `.aex`, parameter settings and preferably paired before/after AE frames: unrelated binaries are intentionally rejected until a separate port is implemented. For Pixel Sorter visual matching, paired AE frames/settings are also needed. EffectCraft itself has **not** been run in this sandbox; the WASM ABI and actual frame processing have been exercised with Node.js and Wasmtime, but in-app loading and AE render parity still need a user check.

The independent AssemblyScript source and manifest are in `effectcraft_plugins/`; the embedded WASM is `effectcraft_pixel_sorter.py`, so source-only updates and locally built Windows EXEs can convert without bundling a toolchain. To **rebuild** the artifact (not required to run it), run `npm install --prefix .venv/wasm-tools --no-save assemblyscript@0.28.20`, then `python3 tools/build_pixel_sorter.py --asc .venv/wasm-tools/node_modules/.bin/asc` (on Windows, use `asc.cmd`). Rebuild the distributable `.wasm` by converting the `.aex` again into a **new** path. Check with `node tests/effectcraft_wasm_smoke.cjs` and the Python tests; the JavaScript smoke test is optional for end users.

## FilmCraft → Premiere limitations (experimental)

The writer constructs a native-style **media → master clip → sequence → track → clip** reference graph from FC items, assigning fresh Premiere object IDs. It handles multiple sequences, tracks, reused media, basic video/audio timings and sequences nested by unambiguous name. Original media are **linked by path, never copied**. For a Graphic clip with **one static, supported `graphic_text` layer**, it embeds the Unicode text, font name, size, fill/stroke, alignment and basic transforms in a Premiere Type-tool `AE.ADBE Text` component with a binary Source Text payload. This makes the title *intended to be editable*, instead of rendering it to an image. Fonts must be installed on the Premiere computer; their metrics and layout may differ. Animated or multi-layer titles and unsupported styles fall back to a separate PNG beside the `.prproj` (requires Pillow); keep any generated PNGs with the project. A missing flatbuffers library also triggers PNG fallback; install all dependencies with `py -3 -m pip install -r requirements.txt`. Both small, neutral graph layouts originate in public MIT fixtures (attribution and licenses in `premiere_seed.py` and `premiere_text_seed.py`), not a project containing your media. An optional empty shell only supplies two build-version strings; it is **not** a guarantee that the graph matches your Premiere version. **The native title has passed structural/payload and timeline round-trip tests, not an Adobe Premiere open, edit or render test.** Diagnostics in the report are currently in Russian even in the English UI.

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
py -3 -m py_compile desktop_app.py aex_to_effectcraft.py effectcraft_pixel_sorter.py project_import.py prproj_to_fcproj.py fcproj_to_prproj.py direct_fc_to_prproj.py graphic_raster.py premiere_seed.py premiere_text.py premiere_text_seed.py reverse_project.py shortcut_converter.py update_converter.py
py -3 -m unittest discover -s tests -v
```

The PySide6 GUI should also be smoke-tested on Windows with real FilmCraft/Premiere projects. Headless UI tests are skipped when system Qt libraries are unavailable (as in the development sandbox); this is not a Windows build or Premiere compatibility test.

## Repository hygiene and privacy

- User projects, test outputs, shortcut profiles, generated `.wasm` files and conversion reports belong in `uploads/` or another local folder and are ignored by Git. The only exception is the 10 KB [ready-to-load WASM sample](effectcraft_plugins/PixelSorter_EffectCraft.wasm). The original `.aex` and installer must not be added to the repository.
- The committed shortcut templates are blank/sanitized catalogs. Do not replace them with personal profiles before publishing. The embedded Premiere graph layouts are adapted from MIT-licensed public fixtures; sources, changes and full license notices are in `premiere_seed.py` and `premiere_text_seed.py`.
- No credentials or user project/media paths are intended to be part of the source release. Run a final repository scan before pushing, especially after adding test fixtures.
- No `LICENSE` file is included. Choose a license before describing the project as open source; without one, normal copyright restrictions apply.

---

# Конвертер Adobe ↔ Craft (Русский)

**Нативная настольная утилита для Windows** с двумя уровнями вкладок: пара программ → тип данных. Работают проекты и горячие клавиши Premiere Pro ↔ FilmCraft, а также независимый порт AE Pixel Sorter 2 → EffectCraft. Остальные направления отмечены «Пока не реализовано». Интерфейс на PySide6, без браузера и веб-сервера. Выбранный русский/английский язык запоминается.

> **Состояние конвертации проектов:** одна очередь принимает Premiere `.prproj` и FilmCraft `.fcproj` и определяет направление по содержимому файла. FilmCraft → Premiere теперь строит новый граф проекта **без заполненного эталона** и без обязательного проекта Premiere. Совместимость с Premiere остаётся экспериментальной: результат нужно открыть и проверить в программе.

## Возможности

- Нативный интерфейс с группами **Premiere Pro ↔ FilmCraft**, **After Effects ↔ EffectCraft**, **Photoshop ↔ PhotoCraft** и подвкладками **Проекты / Горячие клавиши / Плагины**. Неготовые разделы показывают заглушку и подсказку. Все подвкладки используют общий каркас: заголовок, блоки входа и выхода и зону действий; у проектов Premiere/FilmCraft дополнительно сохраняются единая drag-and-drop-очередь и параметры отдельных проектов.
- Конвертация `.prproj` → `.fcproj` с поддержкой части последовательностей, дорожек, клипов, переходов и эффектов.
- Экспериментальная прямая конвертация FilmCraft `.fcproj` → Premiere `.prproj` в той же очереди: медиа, последовательности, дорожки и клипы создаются из ссылок FC; пустая оболочка Premiere необязательна.
- Конвертация Premiere KYS XML ↔ FilmCraft JSON через вкладку **Premiere Pro ↔ FilmCraft → Горячие клавиши** или CLI.
- **Экспериментально:** распознавание AE Pixel Sorter 2 `.aex` и создание самостоятельного работающего WASM-эффекта для EffectCraft; **не** перевод закрытого бинарного кода или гарантия совпадения с рендером AE.
- Отчёты перечисляют неподдерживаемые и несопоставленные элементы; конвертер не угадывает похожие команды.
- Исходные медиа не копируются. Один простой статичный слой `graphic_text` на клипе Graphic кодируется как редактируемый титр Premiere; сложные случаи сохраняются в PNG. Перемещённые файлы нужно перепривязать в целевой программе.

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

## After Effects `.aex` → EffectCraft `.wasm` (пока только Pixel Sorter)

**Готовый эффект:** [PixelSorter_EffectCraft.wasm](effectcraft_plugins/PixelSorter_EffectCraft.wasm) (Plug-in API v1, ID `org.artcraft_converter.pixel_sorter`). В программе EffectCraft откройте **Effect → Load Effect Plug-in…**, выберите `.wasm` и найдите эффект в категории **Stylize**. Также можно поместить файл в папку `Plug-ins` рядом с настройками EffectCraft для загрузки при запуске. Веб-версия EffectCraft WASM-плагины не поддерживает.

Откройте **After Effects ↔ EffectCraft → Плагины**: форма находится прямо на вкладке, отдельно от общей очереди *проектов* Premiere/FilmCraft. Выберите исходный **AE Pixel Sorter 2** `.aex` (допускается `.aex.txt` из загрузки) и **новый** путь `.wasm`. Проекты/горячие клавиши AE, плагины Premiere и все разделы Photoshop/PhotoCraft пока лишь заглушки. То же через CLI без PySide6:

```powershell
py -3 aex_to_effectcraft.py "C:\path\AEPixelSorter2.aex" "C:\path\PixelSorter_effectcraft.wasm"
# Linux/macOS: python3 aex_to_effectcraft.py INPUT.aex OUTPUT.wasm
```

Программа статически проверяет 64-битный Windows PE DLL, экспорты и характерные строки (не более 64 МБ), затем создаёт автономный `.wasm` и соседний `*_conversion_report.md`; существующие файлы не перезаписываются. Для конвертации и запуска не нужны установщик, After Effects, npm или сеть. `.aex` **не исполняется** и **не копируется** в результат, закрытый код не переносится. Неизвестные `.aex` отклоняются: универсального перевода бинарных плагинов Adobe в EffectCraft **нет**. Исходники/пресеты из AE-проекта, внешние Source-слои, Resolution/Zoom и лицензия не переносятся. У 18 параметров (метрики, угол, порог, Highlights/Shadows, группы линий, длина, смещение, размытие, растушёвка, seed, диагностика, прозрачность) **самостоятельная семантика**. Для проверки **другого** плагина пришлите его `.aex`, значения параметров и, желательно, кадры «до/после» из AE: другие бинарники сейчас намеренно отклоняются, пока для них нет отдельного порта. Точное совпадение с коммерческим Pixel Sorter тоже не подтверждено без эталонных кадров. **Сам EffectCraft здесь запустить не удалось**; ABI и обработка кадров проверены в WebAssembly/Node.js и Wasmtime, но открытие в приложении и совпадение с AE ещё нужно проверить.

Независимые исходники AssemblyScript и манифест находятся в `effectcraft_plugins/`, готовый WASM для работы Python/EXE встроен в `effectcraft_pixel_sorter.py`. Обновление исходников загрузит его автоматически; наличие npm при использовании не требуется. Для **пересборки исходника** (не нужно для работы) установите AssemblyScript 0.28.20: `npm install --prefix .venv/wasm-tools --no-save assemblyscript@0.28.20`, затем `python3 tools/build_pixel_sorter.py --asc .venv/wasm-tools/node_modules/.bin/asc` (в Windows: `asc.cmd`). Чтобы обновить распространяемый `.wasm`, ещё раз конвертируйте `.aex` в новый путь. Проверка: `node tests/effectcraft_wasm_smoke.cjs` и Python-тесты; Node.js нужен только разработчику.

## Ограничения FilmCraft → Premiere (экспериментально)

Writer строит нативный граф ссылок **медиа → master clip → последовательность → дорожка → клип** по данным FC и назначает новые идентификаторы объектов Premiere. Поддержаны несколько последовательностей и дорожек, повторное использование медиа, базовые тайминги видео/аудио и вложенные последовательности с однозначным именем. Исходные медиа **не копируются**, а указываются путями из FC. Для клипа Graphic с **одним простым статичным слоем `graphic_text`** в компонент `AE.ADBE Text` записываются текст Unicode, имя шрифта, размер, заливка/обводка, выравнивание и базовые параметры положения: титр *предполагается редактируемым* в Premiere, а не отрисованным в картинку. Шрифт должен быть установлен на компьютере с Premiere; метрики и вёрстка могут отличаться. При нескольких слоях, анимации или неподдерживаемом стиле остаётся отдельный PNG рядом с `.prproj` (нужен Pillow); переносите PNG вместе с проектом. Если не установлен flatbuffers, также используется PNG. Установите зависимости: `py -3 -m pip install -r requirements.txt`. Оба небольших обезличенных каркаса адаптированы из публичных MIT-образцов (атрибуция в `premiere_seed.py` и `premiere_text_seed.py`); проекта Premiere с вашими медиа в них нет. Необязательная пустая оболочка даёт лишь две строки версии сборки и **не гарантирует** совместимость с вашей версией Premiere. **Нативный титр прошёл структурные тесты, проверку бинарных данных и таймлайна, но не проверку открытия, редактирования или рендера в Adobe Premiere.** Диагностика writer в отчёте пока на русском языке.

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
py -3 -m py_compile desktop_app.py aex_to_effectcraft.py effectcraft_pixel_sorter.py project_import.py prproj_to_fcproj.py fcproj_to_prproj.py direct_fc_to_prproj.py graphic_raster.py premiere_seed.py premiere_text.py premiere_text_seed.py reverse_project.py shortcut_converter.py update_converter.py
py -3 -m unittest discover -s tests -v
```

GUI также нужно проверить на Windows с реальными проектами FilmCraft/Premiere. Если системных библиотек Qt нет, headless UI-тесты пропускаются (как в среде разработки); это не проверка Windows-сборки и совместимости с Premiere.

## Чистота репозитория и приватность

- Пользовательские проекты, результаты, профили горячих клавиш, сгенерированные `.wasm` и отчёты храните локально в `uploads/` или другой папке: они исключены из Git. Исключение — один готовый [WASM-эффект](effectcraft_plugins/PixelSorter_EffectCraft.wasm) на 10 КБ. Оригинальные `.aex` и установщик не добавляйте в репозиторий.
- Шаблоны горячих клавиш очищены. Обезличенные каркасы Premiere адаптированы из публичных MIT-fixtures; источники, изменения и тексты лицензий указаны в `premiere_seed.py` и `premiere_text_seed.py`. Перед публикацией проверьте `git status` и добавляемые файлы.
- В исходниках не предполагаются токены, пользовательские пути или медиафайлы; перед push всё равно выполните финальную проверку.
- Файла `LICENSE` нет. Выберите лицензию до заявления, что проект распространяется как open source; без лицензии действуют обычные ограничения авторского права.
