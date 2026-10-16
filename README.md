# FilmCraft Converter

**Native Windows desktop utility** for Premiere Pro project import and shortcut-file conversion. The UI is built with PySide6; it does not start a browser or web server. Interface language can be switched between Russian and English and is remembered between launches.

> **Project-conversion status:** the desktop app currently converts Premiere `.prproj` → FilmCraft `.fcproj`. The reverse writer in `fcproj_to_prproj.py` is an experimental, graph-reference-based prototype; it is not integrated into the desktop queue and is not a general-purpose bidirectional project converter yet.

## Features

- Native desktop UI with drag-and-drop, a project queue, output-folder selection, and RU/EN language switching.
- Premiere Pro `.prproj` → FilmCraft `.fcproj` conversion, including supported sequences, tracks, clips, transitions, and selected effects.
- Premiere KYS XML ↔ FilmCraft keyboard-shortcut JSON conversion from the **Keyboard shortcuts** dialog or CLI.
- Conversion reports list unsupported or unmapped items instead of guessing at command/effect equivalence.
- Project media is referenced, not copied; moved media must be relinked in FilmCraft.

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

`Start_Converter.bat` launches an existing EXE or runs the Python app if its dependencies are installed. The first build needs an internet connection to install dependencies. A Windows EXE must be built on Windows; no prebuilt binary is included in this repository.

## Project conversion: Premiere → FilmCraft

1. Add one or more `.prproj` files by dropping them onto the window or using **Add projects**.
2. Choose an output folder and click **Convert queue**.
3. Each `.fcproj` is accompanied by a `*_conversion_report.md` report.

Supported effects and transitions vary. Some effect parameters, animation/keyframes, masks, plugins, and version-specific settings may be approximated or omitted. Multistream audio routing uses Premiere's `SecondaryIndex`; FilmCraft must support the relevant multistream audio behavior. Review each report and verify the resulting project in FilmCraft.

## Keyboard shortcuts

The desktop dialog accepts a Premiere `.kys` XML file or a FilmCraft shortcut JSON file and detects the direction from the input format. The CLI equivalents are:

```powershell
py -3 shortcut_converter.py my-shortcuts.kys FilmCraft.json `
  --fc-template FilmCraft_Shortcuts_Template.json --language en

py -3 shortcut_converter.py FilmCraft.json Premiere.kys `
  --kys-template Premiere_Shortcuts_Template.kys --language en
```

The bundled template files are **sanitized mapping catalogs**: they contain no user's assigned key combinations. For Premiere output, commands not represented in the FilmCraft mapping may remain unassigned; for FilmCraft output, unmapped commands are reported. If multiple FilmCraft commands map to one Premiere command, only the first is written and the conflict is reported. The crosswalk is intentionally conservative and does not fuzzy-match command names. If you use a personal shortcut profile as an input, keep it private and do not commit it.

## Experimental reverse writer

`fcproj_to_prproj.py` can update an existing Premiere graph reference using a FilmCraft project, and takes an empty Premiere shell for build metadata:

```powershell
py -3 fcproj_to_prproj.py project.fcproj output.prproj `
  --reference populated-reference.prproj --shell empty-premiere-shell.prproj
```

This is **not a general reverse converter**. The FilmCraft project must align with the reference's sequence names, track counts, clip counts, and available media graph. Creating new Premiere media/master-clip/sequence/track graphs, and reverse-mapping effects/transitions, is not implemented. XML parsing and object-reference checks alone do not prove Premiere will open the result. Validate in Premiere Pro before relying on an output.

## Development checks

```powershell
py -3 -m py_compile desktop_app.py prproj_to_fcproj.py fcproj_to_prproj.py shortcut_converter.py
```

The PySide6 GUI should also be smoke-tested on Windows. In the development sandbox used for this source snapshot, the GUI could not be launched because a system Qt dependency (`libxkbcommon`) was missing; this environment limitation is not a Windows build test.

## Repository hygiene and privacy

- User projects, test outputs, shortcut profiles, and conversion reports belong in `uploads/` or another local folder; `/uploads/` and common generated project/report files are excluded by `.gitignore`.
- The committed shortcut templates are blank/sanitized catalogs. Do not replace them with personal profiles before publishing.
- No credentials or user project/media paths are intended to be part of the source release. Run a final repository scan before pushing, especially after adding test fixtures.
- No `LICENSE` file is included. Choose a license before describing the project as open source; without one, normal copyright restrictions apply.

---

# FilmCraft Converter (Русский)

**Нативная настольная утилита для Windows**: импорт проектов Premiere и конвертация файлов горячих клавиш. Интерфейс на PySide6, без браузера и веб-сервера. Язык переключается между русским и английским и запоминается между запусками.

> **Состояние конвертации проектов:** настольное приложение сейчас преобразует Premiere `.prproj` → FilmCraft `.fcproj`. Обратный writer в `fcproj_to_prproj.py` — экспериментальный прототип, работающий от графа-эталона. Он не подключён к очереди приложения и пока не является универсальным двусторонним конвертером проектов.

## Возможности

- Нативный интерфейс: drag-and-drop, очередь проектов, выбор папки результата, переключатель RU/EN.
- Конвертация `.prproj` → `.fcproj` с поддержкой части последовательностей, дорожек, клипов, переходов и эффектов.
- Конвертация Premiere KYS XML ↔ FilmCraft JSON для горячих клавиш через окно приложения или CLI.
- Отчёты перечисляют неподдерживаемые и несопоставленные элементы; конвертер не угадывает похожие команды.
- Исходные медиа не копируются. Перемещённые файлы нужно перепривязать в FilmCraft.

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

`Start_Converter.bat` запускает существующий EXE или исходный код, если зависимости установлены. Для первой сборки нужен интернет, чтобы установить зависимости. EXE нужно собирать на Windows; готового бинарника в репозитории нет.

## Проект Premiere → FilmCraft

1. Перетащите один или несколько `.prproj` в окно или нажмите **Добавить проекты**.
2. Выберите папку результата и нажмите **Конвертировать очередь**.
3. Рядом с каждым `.fcproj` создаётся отчёт `*_conversion_report.md`.

Поддержка эффектов и переходов ограничена: отдельные параметры, ключевые кадры/анимация, маски, плагины и настройки конкретных версий могут переноситься приближённо или пропускаться. Маршрутизация многопоточного аудио использует Premiere `SecondaryIndex`; FilmCraft должен поддерживать соответствующее поведение. Проверяйте отчёт и результат в FilmCraft.

## Горячие клавиши

Окно приложения принимает Premiere `.kys` (XML) или FilmCraft JSON и определяет направление по типу входа. Примеры команд CLI приведены в английской части README; замените `--language en` на `--language ru`, если нужен русский отчёт.

Включённые шаблоны — **очищенные каталоги соответствий** без пользовательских назначений. В выходном KYS команды, не покрытые таблицей FilmCraft, могут остаться без клавиш; неподдерживаемые команды указываются в отчёте. Если несколько FilmCraft-команд сопоставились одной команде Premiere, переносится первая, а конфликт попадает в отчёт. Сопоставление намеренно консервативное. Не добавляйте личные профили горячих клавиш в публичный репозиторий.

## Экспериментальный обратный writer

`fcproj_to_prproj.py` может обновить существующий граф Premiere из FilmCraft-проекта; пустая оболочка Premiere передаётся отдельно для метаданных версии. Команда приведена выше. Это **не универсальная обратная конвертация**: имена последовательностей, число дорожек/клипов и медиа должны соответствовать графу-эталону. Создание новых графов медиа, master clips, последовательностей и дорожек, а также обратный перенос эффектов/переходов пока не реализованы. Проверка XML и ссылок не доказывает, что Premiere откроет файл; проверяйте его в Premiere Pro.

## Проверки разработки

```powershell
py -3 -m py_compile desktop_app.py prproj_to_fcproj.py fcproj_to_prproj.py shortcut_converter.py
```

GUI также нужно проверять на Windows. В среде, где подготовлен этот снимок исходников, Qt GUI не запускался из-за отсутствующей системной библиотеки `libxkbcommon`; это ограничение окружения, а не проверка Windows-сборки.

## Чистота репозитория и приватность

- Пользовательские проекты, тестовые результаты, профили горячих клавиш и отчёты храните локально в `uploads/` или отдельной папке: `/uploads/` и типовые результаты исключены через `.gitignore`.
- В репозитории должны оставаться только очищенные шаблоны. Перед публикацией проверьте `git status` и просканируйте добавленные fixtures.
- В исходниках не предполагаются токены, пользовательские пути или медиафайлы; перед push всё равно выполните финальную проверку.
- Файла `LICENSE` нет. Выберите лицензию до заявления, что проект распространяется как open source; без лицензии действуют обычные ограничения авторского права.
