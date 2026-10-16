# FilmCraft Converter

**Native Windows desktop utility** for Premiere Pro project import and shortcut-file conversion. The UI is built with PySide6; it does not start a browser or web server. Interface language can be switched between Russian and English and is remembered between launches.

> **Project-conversion status:** one desktop queue accepts Premiere `.prproj` and FilmCraft `.fcproj` projects and detects the direction from file content. FilmCraft → Premiere remains **experimental**: each FC item needs a matching populated Premiere reference and an empty Premiere shell. This is not a general-purpose reverse converter.

## Features

- Native desktop UI with drag-and-drop, one mixed project queue, automatic direction detection, output-folder selection, and RU/EN language switching.
- Premiere Pro `.prproj` → FilmCraft `.fcproj` conversion, including supported sequences, tracks, clips, transitions, and selected effects.
- Experimental FilmCraft `.fcproj` → Premiere `.prproj` conversion in the same queue, with per-project fields for a populated Premiere graph reference and an empty Premiere shell.
- Premiere KYS XML ↔ FilmCraft keyboard-shortcut JSON conversion from the **Keyboard shortcuts** dialog or CLI.
- Conversion reports list unsupported or unmapped items instead of guessing at command/effect equivalence.
- Project media is referenced, not copied; moved media must be relinked in the destination app.

## Windows: run from source

Requires Python 3.10+ and Windows.

```powershell
py -3 -m pip install -r requirements.txt
py -3 desktop_app.py
```

## Windows: build a standalone EXE

1. Install Python 3.10+ with the Python Launcher (`py`).
2. Run `Build_Windows_EXE.bat`.
3. The script installs PySide6/PyInstaller, builds `FilmCraftConverter.exe`, and copies it beside the source files.
4. Launch the EXE. Python and a browser are not required to run the built app.

`Start_Converter.bat` prefers a Python source launch so it can check for source updates first. If Python/PySide6 is unavailable, it falls back to an existing EXE, which **is not automatically updated**. The first EXE build needs an internet connection to install dependencies. A Windows EXE must be built on Windows; no prebuilt binary is included in this repository.

### Source auto-updates on launch

With Python 3.10+ installed, the batch file uses `update_converter.py` to inspect **all branches of this repository** and selects the branch whose HEAD has the most recent *committer date* (not necessarily `main`). It downloads that commit's source ZIP from GitHub and runs the downloaded Python app. It checks on each launch; no Git or GitHub account is required. Only download code from this repository if you trust everyone who can push to its branches.

Versions are cached under `%LOCALAPPDATA%\FilmCraftConverter\source-updates\versions\<commit>`. Your checkout, launcher, EXE, user projects, and shortcut profiles are **not overwritten**. If GitHub is offline/rate-limited or an update fails validation, the last cached version is launched (or the local source if none is cached). Set `FILMCRAFT_SKIP_UPDATE=1` before launching to run the local source without a network check. The check is limited to 40 branches because unauthenticated GitHub API requests are rate-limited; when this limit is exceeded, it falls back safely.

This is a **source-only** updater: installing PySide6 is still your responsibility (`py -3 -m pip install -r requirements.txt`). The EXE is neither downloaded nor rebuilt automatically; to update a standalone EXE, rebuild it with `Build_Windows_EXE.bat` or publish a release binary separately.

## Project conversion: shared queue

1. Drag `.prproj` and/or `.fcproj` files onto the window, or click **Add projects**. Premiere XML (`.xml`/`.txt`) and FilmCraft project JSON (`.json`) are also accepted when their contents match a supported project format. The **Direction** column shows PR → FC or FC → PR; shortcut profiles are kept in their separate dialog.
2. For **each FC → PR item**, select its row and provide a matching **populated Premiere reference** and an **empty Premiere shell** in the inline settings panel. PR → FC items need no templates. Both Premiere files must be supplied by you; none are bundled.
3. Choose an output folder and click **Convert queue**. FC items without templates are marked as skipped; configured items (including PR → FC) continue. Output extensions follow the detected direction (`.fcproj` or `.prproj`), and each project gets a sibling `*_conversion_report.md`. Existing output/report names are not replaced; a numbered name is chosen instead.
4. Read the reports and verify results in FilmCraft or Premiere Pro.

**Premiere → FilmCraft:** supported effects and transitions vary. Some effect parameters, animation/keyframes, masks, plugins, and version-specific settings may be approximated or omitted. Multistream audio routing uses Premiere's `SecondaryIndex`; FilmCraft must support the relevant multistream audio behavior.

## Keyboard shortcuts

The desktop dialog accepts a Premiere `.kys` XML file or a FilmCraft shortcut JSON file and detects the direction from the input format. The CLI equivalents are:

```powershell
py -3 shortcut_converter.py my-shortcuts.kys FilmCraft.json `
  --fc-template FilmCraft_Shortcuts_Template.json --language en

py -3 shortcut_converter.py FilmCraft.json Premiere.kys `
  --kys-template Premiere_Shortcuts_Template.kys --language en
```

The bundled template files are **sanitized mapping catalogs**: they contain no user's assigned key combinations. For Premiere output, commands not represented in the FilmCraft mapping may remain unassigned; for FilmCraft output, unmapped commands are reported. If multiple FilmCraft commands map to one Premiere command, only the first is written and the conflict is reported. The crosswalk is intentionally conservative and does not fuzzy-match command names. If you use a personal shortcut profile as an input, keep it private and do not commit it.

## FilmCraft → Premiere limitations (experimental)

The populated reference must contain the **same sequence names, track and clip counts, and media** as the FC project; the empty shell supplies build metadata for your Premiere version. The inline fields are stored **per FC row**, so different projects may use different templates. The native writer's diagnostics in reports are currently in Russian even when the interface is in English.

The CLI uses the same experimental writer:

```powershell
py -3 fcproj_to_prproj.py project.fcproj output.prproj `
  --reference populated-reference.prproj --shell empty-premiere-shell.prproj
```

This is **not a general reverse converter**. Creating new Premiere media/master-clip/sequence/track graphs, and reverse-mapping effects/transitions, is not implemented. XML parsing and object-reference checks alone do not prove Premiere will open the result. Work on copies of your projects and validate in Premiere Pro before relying on an output.

## Development checks

```powershell
py -3 -m py_compile desktop_app.py project_import.py prproj_to_fcproj.py fcproj_to_prproj.py reverse_project.py shortcut_converter.py update_converter.py
py -3 -m unittest discover -s tests -v
```

The PySide6 GUI should also be smoke-tested on Windows with real FilmCraft/Premiere projects. Headless UI tests are skipped when system Qt libraries are unavailable (as in the development sandbox); this is not a Windows build or Premiere compatibility test.

## Repository hygiene and privacy

- User projects, test outputs, shortcut profiles, and conversion reports belong in `uploads/` or another local folder; `/uploads/` and common generated project/report files are excluded by `.gitignore`.
- The committed shortcut templates are blank/sanitized catalogs. Do not replace them with personal profiles before publishing.
- No credentials or user project/media paths are intended to be part of the source release. Run a final repository scan before pushing, especially after adding test fixtures.
- No `LICENSE` file is included. Choose a license before describing the project as open source; without one, normal copyright restrictions apply.

---

# FilmCraft Converter (Русский)

**Нативная настольная утилита для Windows**: импорт проектов Premiere и конвертация файлов горячих клавиш. Интерфейс на PySide6, без браузера и веб-сервера. Язык переключается между русским и английским и запоминается между запусками.

> **Состояние конвертации проектов:** одна очередь принимает Premiere `.prproj` и FilmCraft `.fcproj` и определяет направление по содержимому файла. FilmCraft → Premiere остаётся **экспериментальным**: для каждого FC-проекта нужны заполненный эталон Premiere и пустая оболочка. Это не универсальная обратная конвертация.

## Возможности

- Нативный интерфейс: drag-and-drop, единая очередь разных проектов с автоматическим определением направления, выбор папки результата, RU/EN.
- Конвертация `.prproj` → `.fcproj` с поддержкой части последовательностей, дорожек, клипов, переходов и эффектов.
- Экспериментальная конвертация FilmCraft `.fcproj` → Premiere `.prproj` в той же очереди: эталон Premiere и пустая оболочка задаются отдельно для каждого FC-проекта.
- Конвертация Premiere KYS XML ↔ FilmCraft JSON для горячих клавиш через окно приложения или CLI.
- Отчёты перечисляют неподдерживаемые и несопоставленные элементы; конвертер не угадывает похожие команды.
- Исходные медиа не копируются. Перемещённые файлы нужно перепривязать в целевой программе.

## Запуск из исходников в Windows

Нужны Python 3.10+ и Windows.

```powershell
py -3 -m pip install -r requirements.txt
py -3 desktop_app.py
```

## Сборка EXE в Windows

1. Установите Python 3.10+ с Python Launcher (`py`).
2. Запустите `Build_Windows_EXE.bat`.
3. Скрипт установит PySide6/PyInstaller, соберёт `FilmCraftConverter.exe` и скопирует его рядом с исходниками.
4. Запустите EXE. Для уже собранного приложения Python и браузер не нужны.

`Start_Converter.bat` предпочитает запуск исходников через Python, чтобы сначала проверить обновления. Если Python/PySide6 недоступен, запускается имеющийся EXE, но **он автоматически не обновляется**. Для первой сборки EXE нужен интернет для установки зависимостей. EXE нужно собирать на Windows; готового бинарника в репозитории нет.

### Автообновление исходников при запуске

При наличии Python 3.10+ батник вызывает `update_converter.py`: проверяет **все ветки этого репозитория** и выбирает ту, у которой самый поздний *коммит по дате коммиттера* (это не обязательно `main`). Затем скачивает ZIP исходников именно этого коммита с GitHub и запускает обновлённый код. Проверка проводится при каждом запуске; Git и аккаунт GitHub не нужны. Используйте такой режим, только если доверяете всем, кто может публиковать ветки в репозитории.

Версии сохраняются в `%LOCALAPPDATA%\FilmCraftConverter\source-updates\versions\<commit>`. Исходная папка, батник, EXE, пользовательские проекты и профили клавиш **не перезаписываются**. Если GitHub недоступен, исчерпан лимит API или обновление повреждено, запускается последняя сохранённая версия (либо локальные исходники). Чтобы запустить локальную версию без проверки сети, задайте `FILMCRAFT_SKIP_UPDATE=1`. Из-за лимита GitHub API без авторизации проверяются репозитории не более чем с 40 ветками; при превышении лимита используется резервная версия.

Это обновление **только исходников**: PySide6 нужно установить самостоятельно (`py -3 -m pip install -r requirements.txt`). Готовый EXE не скачивается и не пересобирается автоматически; для него повторно запустите `Build_Windows_EXE.bat` или публикуйте отдельный бинарный релиз.

## Конвертация проектов: общая очередь

1. Перетащите `.prproj` и/или `.fcproj` в окно либо нажмите **Добавить проекты**. Premiere XML (`.xml`/`.txt`) и JSON проекта FilmCraft (`.json`) тоже принимаются, если содержимое соответствует формату проекта. Столбец **Направление** показывает PR → FC или FC → PR; профили горячих клавиш остаются в отдельном окне.
2. Для **каждого элемента FC → PR** выделите строку и укажите в появившейся панели **заполненный эталон Premiere** и **пустую оболочку Premiere**. Для PR → FC шаблоны не нужны. Эти файлы нужно предоставить самостоятельно, в репозитории их нет.
3. Выберите папку вывода и нажмите **Конвертировать очередь**. FC-проекты без шаблонов будут помечены как пропущенные, остальные (включая PR → FC) продолжат обработку. Формат результата (`.fcproj` или `.prproj`) определяется автоматически; рядом создаётся `*_conversion_report.md`. Существующие проекты и отчёты не перезаписываются — выбирается имя с номером.
4. Прочитайте отчёты и проверьте результаты в FilmCraft или Premiere Pro.

**Premiere → FilmCraft:** поддержка эффектов и переходов ограничена: отдельные параметры, ключевые кадры/анимация, маски, плагины и настройки версий могут переноситься приближённо или пропускаться. Маршрутизация многопоточного аудио использует Premiere `SecondaryIndex`; FilmCraft должен поддерживать соответствующее поведение.

## Горячие клавиши

Окно приложения принимает Premiere `.kys` (XML) или FilmCraft JSON и определяет направление по типу входа. Примеры команд CLI приведены в английской части README; замените `--language en` на `--language ru`, если нужен русский отчёт.

Включённые шаблоны — **очищенные каталоги соответствий** без пользовательских назначений. В выходном KYS команды, не покрытые таблицей FilmCraft, могут остаться без клавиш; неподдерживаемые команды указываются в отчёте. Если несколько FilmCraft-команд сопоставились одной команде Premiere, переносится первая, а конфликт попадает в отчёт. Сопоставление намеренно консервативное. Не добавляйте личные профили горячих клавиш в публичный репозиторий.

## Ограничения FilmCraft → Premiere (экспериментально)

Заполненный эталон должен содержать **совпадающие имена последовательностей, число дорожек и клипов, а также медиа**. Пустая оболочка предоставляет метаданные версии Premiere. Параметры задаются **для каждой строки FC отдельно**. После конвертации обязательно откройте результат в Premiere Pro для проверки.

CLI использует тот же экспериментальный writer; пример команды приведён выше. Это **не универсальная обратная конвертация**: создание новых графов медиа, master clips, последовательностей и дорожек, а также обратный перенос эффектов/переходов пока не реализованы. Проверка XML и ссылок не доказывает, что Premiere откроет файл. Работайте с копиями проектов и проверяйте результат в Premiere Pro.

## Проверки разработки

```powershell
py -3 -m py_compile desktop_app.py project_import.py prproj_to_fcproj.py fcproj_to_prproj.py reverse_project.py shortcut_converter.py update_converter.py
py -3 -m unittest discover -s tests -v
```

GUI также нужно проверить на Windows с реальными проектами FilmCraft/Premiere. Если системных библиотек Qt нет, headless UI-тесты пропускаются (как в среде разработки); это не проверка Windows-сборки и совместимости с Premiere.

## Чистота репозитория и приватность

- Пользовательские проекты, тестовые результаты, профили горячих клавиш и отчёты храните локально в `uploads/` или отдельной папке: `/uploads/` и типовые результаты исключены через `.gitignore`.
- В репозитории должны оставаться только очищенные шаблоны. Перед публикацией проверьте `git status` и просканируйте добавленные fixtures.
- В исходниках не предполагаются токены, пользовательские пути или медиафайлы; перед push всё равно выполните финальную проверку.
- Файла `LICENSE` нет. Выберите лицензию до заявления, что проект распространяется как open source; без лицензии действуют обычные ограничения авторского права.
