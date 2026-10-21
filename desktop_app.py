#!/usr/bin/env python3
"""Native desktop UI grouped by application pair, then project/hotkey/plug-in.
Built with PySide6. No browser/server is used.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout,
    QHBoxLayout, QProgressBar, QMessageBox, QAbstractItemView, QSizePolicy, QComboBox,
    QScrollArea, QCheckBox, QTabWidget,
)
from project_import import FC_TO_PR, ProjectTypeError, convert_queued_project, detect_project_direction
from reverse_project import ReportWriteError
from shortcut_converter import convert_fc_to_kys, convert_kys_to_fc
from aex_to_effectcraft import convert_aex, output_stem

APP_NAME='Adobe Craft Converter'

TEXT = {
    'ru': {
        'window_title':'Конвертер Adobe ↔ Craft','header_title':'Adobe  ↔  Craft',
        'subtitle':'Выберите пару программ и тип данных · локальная конвертация',
        'tab_projects':'Проекты','tab_hotkeys':'Горячие клавиши','tab_plugins':'Плагины',
        'planned_suffix':' · скоро','planned_title':'Пока не реализовано',
        'planned_note':'Конвертация «{feature}» для {pair} пока не реализована. Здесь появится инструмент, когда он будет готов; файлы не изменяются.',
        'planned_tooltip':'Пока не реализовано: {feature} · {pair}',
        'source_data':'ИСХОДНЫЕ ДАННЫЕ','target_data':'РЕЗУЛЬТАТ',
        'planned_source':'Для этого типа данных конвертер пока недоступен.',
        'planned_target':'Файлы результата не создаются.',
        'project_heading':'Проекты · Premiere ↔ FilmCraft',
        'project_note':'Добавляйте проекты в общую очередь: направление определяется автоматически. Для FC → PR дополнительные параметры доступны при выборе проекта.',
        'source_projects':'ИСХОДНЫЕ ПРОЕКТЫ',
        'source_shortcuts':'ИСХОДНЫЙ ПРОФИЛЬ','target_shortcuts':'ФАЙЛ РЕЗУЛЬТАТА',
        'source_plugin':'ИСХОДНЫЙ ПЛАГИН','target_plugin':'WASM-ЭФФЕКТ',
        'language':'Язык / Language','local_app':'ЛОКАЛЬНОЕ ПРИЛОЖЕНИЕ','drop_title':'Перетащите .prproj или .fcproj сюда',
        'drop_note':'Направление определяется по содержимому файла · можно добавить несколько проектов','add':'＋  Добавить проекты',
        'remove':'Удалить выбранные','clear':'Очистить очередь','output_folder':'ПАПКА ВЫВОДА','configurable':'настраивается',
        'output_placeholder':'Папка для результатов .fcproj и .prproj','browse':'Обзор…','queue':'ОЧЕРЕДЬ','project':'Проект','direction':'Направление',
        'status':'Статус','result':'Результат','ready':'Готов к работе','open_folder':'Открыть папку',
        'convert_queue':'Конвертировать очередь','footnote':'Исходные медиа не копируются. Простой текст Graphic создаётся как редактируемый титр; остальные Graphic — PNG. FC → PR экспериментален: проверьте результат в Premiere.',
        'state_pending':'Ожидает','state_running':'Конвертация…','state_done':'Готово','state_error':'Ошибка','dash':'—',
        'count_zero':'0 проектов','count_projects':'{n} проектов','count_one':'{n} проект','count_few':'{n} проекта',
        'added':'Добавлено в очередь: {n}','queue_cleared':'Очередь очищена','folder_error_title':'Папка недоступна',
        'processing':'Обработка {done} из {total}','converting':'Конвертация: {name}','done':'Готово: {name}',
'done_warnings':'Готово: {name} · сообщений в отчёте: {n}','failed':'Ошибка: {name}','queue_finished':'Очередь завершена',
        'close_running_title':'Конвертация выполняется','close_running_text':'Дождитесь завершения очереди, чтобы не прерывать запись проекта.',
        'add_dialog':'Выберите проекты Premiere или FilmCraft','project_filter':'Проекты (*.prproj *.fcproj *.json *.xml *.txt);;Все файлы (*)','premiere_filter':'Проекты Premiere/XML (*.prproj *.xml *.txt);;Все файлы (*)',
        'output_dialog':'Папка для конвертированных проектов',
        'shortcut_heading':'Premiere KYS ↔ FilmCraft JSON',
        'shortcut_note':'Выберите .kys (XML) или JSON FilmCraft. Направление определяется автоматически; команды без соответствия будут указаны в отчёте.',
        'shortcut_input_placeholder':'Исходный файл .kys или FilmCraft shortcuts .json','shortcut_file':'Файл…',
        'shortcut_output_placeholder':'Файл результата','save_as':'Сохранить как…','convert':'Конвертировать',
        'choose_shortcut_file':'Выберите файл горячих клавиш','shortcut_filter':'Горячие клавиши (*.kys *.json *.txt);;Все файлы (*)',
        'save_shortcuts':'Сохранить набор горячих клавиш','shortcut_save_filter':'FilmCraft JSON (*.json);;Premiere KYS (*.kys)',
        'no_source_title':'Нет исходного файла','no_source':'Выберите существующий файл .kys или FilmCraft JSON.',
        'no_output_title':'Нет файла результата','no_output':'Укажите имя выходного файла.','conversion_done':'Конвертация завершена',
        'file_created':'Файл создан:\n{path}\n\n{summary}\nПодробности: {report}',
        'conversion_error':'Ошибка конвертации','report_title':'Отчёт конвертации горячих клавиш',
        'report_input':'Вход','report_output':'Выход','report_result':'Результат',
        'shortcut_summary_default':'Конвертация выполнена. См. отчёт для списка назначений и предупреждений.',
        'dir_pr_fc':'PR → FC','dir_fc_pr':'FC → PR · эксперим.',
        'reverse_heading':'ПАРАМЕТРЫ FC → PR · {name}',
        'reverse_note':'Прямой FC → PR не требует заполненного проекта Premiere. Пустая оболочка необязательна. Простой статичный Graphic-текст преобразуется в редактируемый титр; для сложных случаев остаётся PNG. Проверьте результат в Premiere Pro.',
        'raster_checkbox':'Использовать PNG для Graphic (режим совместимости, текст не редактируется)',
        'shell_label':'Пустая оболочка (необязательно)',
        'shell_placeholder':'Пустой .prproj вашей версии, необязательно',
        'choose_shell_project':'Выберите пустую оболочку Premiere (необязательно)',
        'no_shell':'Указанная пустая оболочка для «{name}» не найдена.',
        'templates_needed_title':'Недоступна оболочка Premiere','templates_needed':'Эти проекты пропущены:\n{details}\n\nУдалите путь или выберите существующую оболочку. Остальные проекты будут обработаны.',
        'invalid_title':'Не удалось добавить проекты','invalid_header':'Пропущены файлы:','invalid_extension':'неподдерживаемое расширение','invalid_format':'не распознан проект Premiere или FilmCraft','invalid_shortcut':'файл горячих клавиш — откройте вкладку «Горячие клавиши»','invalid_missing':'файл не найден','invalid_more':'…и ещё {n}',
        'report_write_failed':'Проект создан, но не удалось сохранить отчёт: {error}',
        'plugin_heading':'AE Pixel Sorter 2 → EffectCraft',
        'plugin_note':'Только распознанный AE Pixel Sorter 2. Создаётся самостоятельный рабочий WASM-эффект сортировки пикселей, а не копия/перевод закрытого .aex. Установщик не нужен. Визуальное совпадение с AE не гарантировано.',
        'plugin_input':'Исходный файл AE Pixel Sorter 2 .aex', 'plugin_output':'Новый файл плагина .wasm',
        'plugin_choose':'Выберите AE Pixel Sorter 2 .aex',
        'plugin_filter':'Плагины Adobe (*.aex *.aex.txt);;Все файлы (*)',
        'plugin_save':'Сохранить независимый плагин EffectCraft',
        'plugin_save_filter':'Плагин EffectCraft (*.wasm)',
        'plugin_missing':'Выберите существующий файл AE Pixel Sorter 2 .aex.',
        'plugin_summary':'WASM с 18 параметрами. Это независимая реализация, а не оригинал; подробности и ограничения в отчёте.',
    },
    'en': {
        'window_title':'Adobe ↔ Craft Converter','header_title':'Adobe  ↔  Craft',
        'subtitle':'Choose an application pair and data type · local conversion',
        'tab_projects':'Projects','tab_hotkeys':'Hotkeys','tab_plugins':'Plugins',
        'planned_suffix':' · planned','planned_title':'Not implemented yet',
        'planned_note':'Conversion of {feature} for {pair} is not implemented yet. A tool will appear here when support is added; no files are changed.',
        'planned_tooltip':'Not implemented yet: {feature} · {pair}',
        'source_data':'SOURCE DATA','target_data':'RESULT',
        'planned_source':'Conversion for this data type is not available yet.',
        'planned_target':'No output files are created.',
        'project_heading':'Projects · Premiere ↔ FilmCraft',
        'project_note':'Add projects to one queue: direction is detected automatically. Select an FC project to set optional FC → PR parameters.',
        'source_projects':'SOURCE PROJECTS',
        'source_shortcuts':'SOURCE SHORTCUTS','target_shortcuts':'OUTPUT FILE',
        'source_plugin':'SOURCE PLUG-IN','target_plugin':'WASM EFFECT',
        'language':'Language / Язык','local_app':'LOCAL DESKTOP APP','drop_title':'Drop .prproj or .fcproj files here',
        'drop_note':'Direction is detected from file content · add multiple projects','add':'＋  Add projects',
        'remove':'Remove selected','clear':'Clear queue','output_folder':'OUTPUT FOLDER','configurable':'configurable',
        'output_placeholder':'Output folder for .fcproj and .prproj','browse':'Browse…','queue':'QUEUE','project':'Project','direction':'Direction',
        'status':'Status','result':'Result','ready':'Ready','open_folder':'Open folder',
        'convert_queue':'Convert queue','footnote':'Original media is linked, not copied. Simple Graphic text becomes an editable title; unsupported Graphics generate PNGs. FC → PR is experimental: verify in Premiere.',
        'state_pending':'Pending','state_running':'Converting…','state_done':'Done','state_error':'Error','dash':'—',
        'count_zero':'0 projects','count_projects':'{n} projects','count_one':'{n} project','count_few':'{n} projects',
        'added':'Added to queue: {n}','queue_cleared':'Queue cleared','folder_error_title':'Folder unavailable',
        'processing':'Processing {done} of {total}','converting':'Converting: {name}','done':'Done: {name}',
'done_warnings':'Done: {name} · report messages: {n}','failed':'Error: {name}','queue_finished':'Queue finished',
        'close_running_title':'Conversion in progress','close_running_text':'Wait for the queue to finish so project files are not interrupted during writing.',
        'add_dialog':'Select Premiere or FilmCraft projects','project_filter':'Projects (*.prproj *.fcproj *.json *.xml *.txt);;All files (*)','premiere_filter':'Premiere/XML projects (*.prproj *.xml *.txt);;All files (*)',
        'output_dialog':'Converted projects folder',
        'shortcut_heading':'Premiere KYS ↔ FilmCraft JSON',
        'shortcut_note':'Choose a Premiere .kys (XML) or FilmCraft JSON file. Direction is detected automatically; unmapped commands are listed in the report.',
        'shortcut_input_placeholder':'Input .kys or FilmCraft shortcuts .json file','shortcut_file':'Browse…',
        'shortcut_output_placeholder':'Output file','save_as':'Save as…','convert':'Convert',
        'choose_shortcut_file':'Choose a shortcut file','shortcut_filter':'Shortcuts (*.kys *.json *.txt);;All files (*)',
        'save_shortcuts':'Save shortcut set','shortcut_save_filter':'FilmCraft JSON (*.json);;Premiere KYS (*.kys)',
        'no_source_title':'No input file','no_source':'Choose an existing .kys or FilmCraft JSON file.',
        'no_output_title':'No output file','no_output':'Specify an output filename.','conversion_done':'Conversion complete',
        'file_created':'Created file:\n{path}\n\n{summary}\nDetails: {report}',
        'conversion_error':'Conversion error','report_title':'Keyboard shortcut conversion report',
        'report_input':'Input','report_output':'Output','report_result':'Result',
        'shortcut_summary_default':'Conversion complete. See the report for transferred shortcuts and warnings.',
        'dir_pr_fc':'PR → FC','dir_fc_pr':'FC → PR · experimental',
        'reverse_heading':'FC → PR SETTINGS · {name}',
        'reverse_note':'Direct FC → PR needs no populated Premiere project; an empty shell is optional. Simple static Graphic text becomes an editable title; complex cases still use PNG. Verify the result in Premiere Pro.',
        'raster_checkbox':'Use PNG for Graphic (compatibility mode; text is not editable)',
        'shell_label':'Empty shell (optional)',
        'shell_placeholder':'Empty .prproj from your version, optional',
        'choose_shell_project':'Choose an empty Premiere shell (optional)',
        'no_shell':'The selected empty shell for “{name}” was not found.',
        'templates_needed_title':'Premiere shell unavailable','templates_needed':'These projects were skipped:\n{details}\n\nClear the path or select an existing empty shell. Other projects will continue.',
        'invalid_title':'Could not add projects','invalid_header':'Skipped files:','invalid_extension':'unsupported extension','invalid_format':'not a recognized Premiere or FilmCraft project','invalid_shortcut':'shortcut file — use the Hotkeys tab','invalid_missing':'file not found','invalid_more':'…and {n} more',
        'report_write_failed':'Project created, but the report could not be saved: {error}',
        'plugin_heading':'AE Pixel Sorter 2 → EffectCraft',
        'plugin_note':'Recognized AE Pixel Sorter 2 only. Generates a working, independently written pixel-sorting WASM effect, not a copy or translation of the closed-source .aex. No installer required. AE visual parity is not guaranteed.',
        'plugin_input':'Input AE Pixel Sorter 2 .aex', 'plugin_output':'New .wasm effect file',
        'plugin_choose':'Choose AE Pixel Sorter 2 .aex',
        'plugin_filter':'Adobe plug-ins (*.aex *.aex.txt);;All files (*)',
        'plugin_save':'Save independent EffectCraft plug-in',
        'plugin_save_filter':'EffectCraft plug-in (*.wasm)',
        'plugin_missing':'Choose an existing AE Pixel Sorter 2 .aex file.',
        'plugin_summary':'WASM effect with 18 controls. This is an independent implementation; see the report for its limitations.',
    }
}

def tr(language: str, key: str, **values) -> str:
    language = 'en' if language == 'en' else 'ru'
    text = TEXT[language].get(key, TEXT['ru'].get(key, key))
    return text.format(**values) if values else text


def unique_path(directory: Path, stem: str, suffix: str) -> Path:
    candidate=directory/f'{stem}{suffix}'
    n=2
    while candidate.exists():
        candidate=directory/f'{stem}_{n}{suffix}';n+=1
    return candidate


def resource_path(name: str) -> Path:
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    return base/name


class FeaturePage(QScrollArea):
    """Shared structure for every project, hotkey, plug-in and planned subtab.

    Each page has the same scrollable header, source/target cards, details area,
    action row and optional footnote. Only the contents of those slots vary.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.root = QVBoxLayout(content)
        self.root.setContentsMargins(18, 18, 18, 18)
        self.root.setSpacing(12)
        self.title_label = QLabel()
        self.title_label.setObjectName('formTitle')
        self.root.addWidget(self.title_label)
        self.note_label = QLabel()
        self.note_label.setObjectName('muted')
        self.note_label.setWordWrap(True)
        self.root.addWidget(self.note_label)
        (self.source_panel, self.source_title, self.source_meta,
         self.source_layout) = self._section()
        (self.target_panel, self.target_title, self.target_meta,
         self.target_layout) = self._section()
        self.details_layout = QVBoxLayout()
        self.details_layout.setSpacing(12)
        self.root.addLayout(self.details_layout, 1)
        self.footer_layout = QHBoxLayout()
        self.footer_layout.setSpacing(10)
        self.root.addLayout(self.footer_layout)
        self.footnote_label = QLabel()
        self.footnote_label.setObjectName('footnote')
        self.footnote_label.setWordWrap(True)
        self.footnote_label.hide()
        self.root.addWidget(self.footnote_label)
        self.setWidget(content)

    def _section(self):
        panel = QFrame()
        panel.setObjectName('panel')
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel()
        title.setObjectName('section')
        meta = QLabel()
        meta.setObjectName('muted')
        meta.hide()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(meta)
        layout.addLayout(header)
        contents = QVBoxLayout()
        contents.setSpacing(8)
        layout.addLayout(contents)
        self.root.addWidget(panel)
        return panel, title, meta, contents

    @staticmethod
    def file_row(layout):
        row = QHBoxLayout()
        edit = QLineEdit()
        button = QPushButton()
        row.addWidget(edit, 1)
        row.addWidget(button)
        layout.addLayout(row)
        return edit, button


class FileConverterPanel(FeaturePage):
    """Common input/output rows and action/status footer for file converters."""

    def __init__(self, parent=None, language='ru'):
        super().__init__(parent)
        self.language = language
        self.input_edit, self.input_btn = self.file_row(self.source_layout)
        self.input_btn.clicked.connect(self.choose_input)
        self.output_edit, self.output_btn = self.file_row(self.target_layout)
        self.output_btn.clicked.connect(self.choose_output)
        self.status_label = QLabel()
        self.status_label.setObjectName('status')
        self.footer_layout.addWidget(self.status_label, 1)
        self.run_btn = QPushButton()
        self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self.convert)
        self.footer_layout.addWidget(self.run_btn)
        self.last_status = ('ready', {})

    def set_status(self, key, **values):
        self.last_status = (key, values)
        self.status_label.setText(tr(self.language, key, **values))


class ShortcutConverterPanel(FileConverterPanel):
    """Premiere ↔ FilmCraft shortcut conversion, embedded in its own subtab."""

    def __init__(self, parent=None, language='ru'):
        super().__init__(parent, language)
        self.retranslate()

    def retranslate(self):
        self.title_label.setText(tr(self.language, 'shortcut_heading'))
        self.note_label.setText(tr(self.language, 'shortcut_note'))
        self.source_title.setText(tr(self.language, 'source_shortcuts'))
        self.target_title.setText(tr(self.language, 'target_shortcuts'))
        self.status_label.setText(tr(self.language, self.last_status[0], **self.last_status[1]))
        self.input_edit.setPlaceholderText(tr(self.language, 'shortcut_input_placeholder'))
        self.input_btn.setText(tr(self.language, 'shortcut_file'))
        self.output_edit.setPlaceholderText(tr(self.language, 'shortcut_output_placeholder'))
        self.output_btn.setText(tr(self.language, 'save_as'))
        self.run_btn.setText(tr(self.language, 'convert'))

    def choose_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr(self.language, 'choose_shortcut_file'), '',
            tr(self.language, 'shortcut_filter'))
        if not path:
            return
        self.input_edit.setText(path)
        p = Path(path)
        is_json = p.suffix.lower() == '.json'
        if is_json:
            try:
                is_json = json.loads(p.read_text(encoding='utf-8-sig')).get('format') == 'filmcraft-keyboard-shortcuts'
            except Exception:
                is_json = False
        if p.suffix.lower() == '.kys' or p.name.lower().endswith('.kys.txt') or not is_json:
            stem = p.name[:-len('.kys.txt')] if p.name.lower().endswith('.kys.txt') else p.stem
            output = p.with_name(stem + '.json')
        else:
            output = p.with_suffix('.kys')
        if output.exists():
            output = unique_path(output.parent, output.stem, output.suffix)
        self.output_edit.setText(str(output))

    def choose_output(self):
        current = self.output_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, tr(self.language, 'save_shortcuts'), current,
            tr(self.language, 'shortcut_save_filter'))
        if path:
            self.output_edit.setText(path)

    def convert(self):
        raw_output = self.output_edit.text().strip()
        source = Path(self.input_edit.text().strip())
        if not source.is_file():
            self.set_status('state_error')
            QMessageBox.warning(self, tr(self.language, 'no_source_title'),
                                tr(self.language, 'no_source'))
            return
        if not raw_output:
            self.set_status('state_error')
            QMessageBox.warning(self, tr(self.language, 'no_output_title'),
                                tr(self.language, 'no_output'))
            return
        output = Path(raw_output)
        try:
            is_json = (source.suffix.lower() == '.json'
                       and json.loads(source.read_text(encoding='utf-8-sig')).get('format')
                       == 'filmcraft-keyboard-shortcuts')
            if is_json:
                warnings = convert_fc_to_kys(source, output,
                                             resource_path('Premiere_Shortcuts_Template.kys'),
                                             self.language)
            else:
                warnings = convert_kys_to_fc(source, output,
                                             resource_path('FilmCraft_Shortcuts_Template.json'),
                                             self.language)
            report = output.with_name(output.stem + '_shortcuts_report.md')
            report.write_text(
                f'# {tr(self.language, "report_title")}\n\n'
                f'- {tr(self.language, "report_input")}: `{source.name}`\n'
                f'- {tr(self.language, "report_output")}: `{output.name}`\n\n'
                f'## {tr(self.language, "report_result")}\n\n'
                + '\n'.join('- ' + x for x in warnings) + '\n', encoding='utf-8')
            self.set_status('done', name=output.name)
            QMessageBox.information(
                self, tr(self.language, 'conversion_done'),
                tr(self.language, 'file_created', path=output,
                   summary=warnings[0] if warnings else tr(self.language, 'shortcut_summary_default'),
                   report=report.name))
        except Exception as exc:
            self.set_status('state_error')
            QMessageBox.critical(self, tr(self.language, 'conversion_error'), str(exc))


class AexConverterPanel(FileConverterPanel):
    """Independent AE Pixel Sorter port, embedded in After Effects plug-ins tab."""

    def __init__(self, parent=None, language='ru'):
        super().__init__(parent, language)
        self.retranslate()

    def retranslate(self):
        self.title_label.setText(tr(self.language, 'plugin_heading'))
        self.note_label.setText(tr(self.language, 'plugin_note'))
        self.source_title.setText(tr(self.language, 'source_plugin'))
        self.target_title.setText(tr(self.language, 'target_plugin'))
        self.status_label.setText(tr(self.language, self.last_status[0], **self.last_status[1]))
        self.input_edit.setPlaceholderText(tr(self.language, 'plugin_input'))
        self.input_btn.setText(tr(self.language, 'shortcut_file'))
        self.output_edit.setPlaceholderText(tr(self.language, 'plugin_output'))
        self.output_btn.setText(tr(self.language, 'save_as'))
        self.run_btn.setText(tr(self.language, 'convert'))

    def choose_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr(self.language, 'plugin_choose'), '',
            tr(self.language, 'plugin_filter'))
        if not path:
            return
        self.input_edit.setText(path)
        source = Path(path)
        stem = output_stem(source) + '_effectcraft'
        n = 1
        while True:
            suffix = '' if n == 1 else f'_{n}'
            output = source.with_name(stem + suffix + '.wasm')
            report = output.with_name(output.stem + '_conversion_report.md')
            if not output.exists() and not report.exists():
                break
            n += 1
        self.output_edit.setText(str(output))

    def choose_output(self):
        current = self.output_edit.text().strip() or str(Path.home())
        path, _ = QFileDialog.getSaveFileName(
            self, tr(self.language, 'plugin_save'), current,
            tr(self.language, 'plugin_save_filter'))
        if path:
            self.output_edit.setText(path)

    def convert(self):
        source = Path(self.input_edit.text().strip())
        if not source.is_file():
            self.set_status('state_error')
            QMessageBox.warning(self, tr(self.language, 'no_source_title'),
                                tr(self.language, 'plugin_missing'))
            return
        raw_output = self.output_edit.text().strip()
        if not raw_output:
            self.set_status('state_error')
            QMessageBox.warning(self, tr(self.language, 'no_output_title'),
                                tr(self.language, 'no_output'))
            return
        output = Path(raw_output)
        try:
            report = convert_aex(source, output, language=self.language)
            self.set_status('done', name=output.name)
            QMessageBox.information(
                self, tr(self.language, 'conversion_done'),
                tr(self.language, 'file_created', path=output,
                   summary=tr(self.language, 'plugin_summary'), report=report))
        except Exception as exc:
            self.set_status('state_error')
            QMessageBox.critical(self, tr(self.language, 'conversion_error'), str(exc))


class PlannedFeature(FeaturePage):
    """Non-converting placeholder with the same page structure as live tabs."""

    def __init__(self, program: str, feature: str, language: str):
        super().__init__()
        self.program = program
        self.feature = feature
        self.source_message = QLabel()
        self.source_message.setObjectName('muted')
        self.source_message.setWordWrap(True)
        self.source_layout.addWidget(self.source_message)
        self.target_message = QLabel()
        self.target_message.setObjectName('muted')
        self.target_message.setWordWrap(True)
        self.target_layout.addWidget(self.target_message)
        self.status_label = QLabel()
        self.status_label.setObjectName('status')
        self.footer_layout.addWidget(self.status_label, 1)
        self.retranslate(language)

    def retranslate(self, language: str):
        self.title_label.setText(tr(language, 'planned_title'))
        self.note_label.setText(tr(language, 'planned_note', pair=self.program,
                                   feature=tr(language, 'tab_' + self.feature)))
        self.source_title.setText(tr(language, 'source_data'))
        self.target_title.setText(tr(language, 'target_data'))
        self.source_message.setText(tr(language, 'planned_source'))
        self.target_message.setText(tr(language, 'planned_target'))
        self.status_label.setText(tr(language, 'planned_title'))


class DropArea(QFrame):
    filesDropped=Signal(list)
    def __init__(self, language='ru'):
        super().__init__();self.language=language;self.setAcceptDrops(True);self.setObjectName('dropArea')
        self.setMinimumHeight(150);self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        lay=QVBoxLayout(self);lay.setAlignment(Qt.AlignCenter);lay.setSpacing(6)
        icon=QLabel('↥');icon.setObjectName('dropIcon');icon.setAlignment(Qt.AlignCenter)
        self.title_label=QLabel();self.title_label.setObjectName('dropTitle');self.title_label.setAlignment(Qt.AlignCenter)
        self.note_label=QLabel();self.note_label.setObjectName('muted');self.note_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon);lay.addWidget(self.title_label);lay.addWidget(self.note_label);self.retranslate()
    def retranslate(self):
        self.title_label.setText(tr(self.language,'drop_title'))
        self.note_label.setText(tr(self.language,'drop_note'))
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction();self.setProperty('dragging',True);self.style().unpolish(self);self.style().polish(self)
        else:event.ignore()
    def dragLeaveEvent(self,event):
        self.setProperty('dragging',False);self.style().unpolish(self);self.style().polish(self);event.accept()
    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        self.setProperty('dragging',False);self.style().unpolish(self);self.style().polish(self)
        if paths:self.filesDropped.emit(paths);event.acceptProposedAction()
        else:event.ignore()


class ConversionWorker(QThread):
    fileStarted = Signal(int)
    fileSucceeded = Signal(int, str, int)
    fileFailed = Signal(int, str, str)
    queueFinished = Signal()

    def __init__(self, records: list[tuple[int, dict]], output_dir: Path, language='ru'):
        super().__init__()
        self.records = records
        self.output_dir = output_dir
        self.language = language

    def run(self):
        for index, record in self.records:
            if self.isInterruptionRequested():
                break
            self.fileStarted.emit(index)
            try:
                destination, messages = convert_queued_project(record, self.output_dir, self.language)
                self.fileSucceeded.emit(index, str(destination), messages)
            except ReportWriteError as exc:
                # The Premiere file exists even though its report could not be saved.
                # ReportWriteError carries the output path to avoid guessing a
                # destination after the converter has already created a file.
                self.fileFailed.emit(index, str(exc), str(exc.output))
            except Exception as exc:
                self.fileFailed.emit(index, str(exc) or type(exc).__name__, '')
        self.queueFinished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('FilmCraftTools', 'PRPROJConverter')
        self.language = self.settings.value('language', 'ru', type=str)
        if self.language not in ('ru', 'en'):
            self.language = 'ru'
        self.resize(1050, 870)
        self.setMinimumSize(790, 630)
        self.files: list[dict] = []
        self.worker = None
        self.busy = False
        self._loading_reverse = False
        self.last_status = ('ready', {})

        shell = QWidget()
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        self.header_title = QLabel()
        self.header_title.setObjectName('title')
        self.header_title.setTextFormat(Qt.RichText)
        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName('muted')
        brand.addWidget(self.header_title)
        brand.addWidget(self.subtitle_label)
        header.addLayout(brand)
        header.addStretch()
        self.language_combo = QComboBox()
        self.language_combo.addItem('Русский', 'ru')
        self.language_combo.addItem('English', 'en')
        self.language_combo.setCurrentIndex(0 if self.language == 'ru' else 1)
        self.language_combo.currentIndexChanged.connect(self.language_changed)
        header.addWidget(self.language_combo, 0, Qt.AlignTop)
        self.local_tag = QLabel()
        self.local_tag.setObjectName('tag')
        header.addWidget(self.local_tag, 0, Qt.AlignTop)
        outer.addLayout(header)

        # Program pair first; each pair then has its own data-type tabs.
        # The existing mixed PR/FC project queue remains ONE inline page.
        self.program_tabs = QTabWidget()
        self.program_tabs.setObjectName('programTabs')
        outer.addWidget(self.program_tabs, 1)
        self.premiere_tabs = QTabWidget()
        self.after_effects_tabs = QTabWidget()
        self.photoshop_tabs = QTabWidget()
        for tabs in (self.premiere_tabs, self.after_effects_tabs, self.photoshop_tabs):
            tabs.setObjectName('featureTabs')
        self.program_tabs.addTab(self.premiere_tabs, 'Premiere Pro ↔ FilmCraft')
        self.program_tabs.addTab(self.after_effects_tabs, 'After Effects ↔ EffectCraft')
        self.program_tabs.addTab(self.photoshop_tabs, 'Photoshop ↔ PhotoCraft')

        # The project queue uses the same page slots as every other subtab.
        self.project_page = FeaturePage(self.premiere_tabs)
        self.drop = DropArea(self.language)
        self.drop.filesDropped.connect(self.add_paths)
        self.project_page.source_layout.addWidget(self.drop)
        actions = QHBoxLayout()
        self.add_btn = QPushButton()
        self.add_btn.clicked.connect(self.choose_files)
        self.remove_btn = QPushButton()
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn = QPushButton()
        self.clear_btn.clicked.connect(self.clear_queue)
        actions.addWidget(self.add_btn)
        actions.addWidget(self.remove_btn)
        actions.addStretch()
        actions.addWidget(self.clear_btn)
        self.project_page.source_layout.addLayout(actions)

        self.output_title = self.project_page.target_title
        self.output_note = self.project_page.target_meta
        self.output_note.show()
        self.output_edit, self.browse_btn = self.project_page.file_row(
            self.project_page.target_layout)
        self.output_edit.setText(self.settings.value('output_dir', '', type=str))
        self.browse_btn.clicked.connect(self.choose_output_dir)

        queue_panel = QFrame()
        queue_panel.setObjectName('panel')
        queue_layout = QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(16, 12, 16, 12)
        queue_layout.setSpacing(8)
        qhead = QHBoxLayout()
        self.queue_title = QLabel()
        self.queue_title.setObjectName('section')
        self.count_label = QLabel()
        self.count_label.setObjectName('muted')
        qhead.addWidget(self.queue_title)
        qhead.addStretch()
        qhead.addWidget(self.count_label)
        queue_layout.addLayout(qhead)
        self.table = QTableWidget(0, 4)
        for index, mode in enumerate((QHeaderView.Stretch, QHeaderView.ResizeToContents,
                                      QHeaderView.ResizeToContents, QHeaderView.Stretch)):
            self.table.horizontalHeader().setSectionResizeMode(index, mode)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(155)
        self.table.currentCellChanged.connect(self.update_reverse_panel)
        queue_layout.addWidget(self.table, 1)
        self.project_page.details_layout.addWidget(queue_panel, 1)

        # These controls belong to the selected FC entry, not to the whole queue.
        self.reverse_panel = QFrame()
        self.reverse_panel.setObjectName('panel')
        reverse_layout = QVBoxLayout(self.reverse_panel)
        reverse_layout.setContentsMargins(16, 12, 16, 12)
        reverse_layout.setSpacing(8)
        self.reverse_heading = QLabel()
        self.reverse_heading.setObjectName('section')
        self.reverse_note = QLabel()
        self.reverse_note.setObjectName('muted')
        self.reverse_note.setWordWrap(True)
        reverse_layout.addWidget(self.reverse_heading)
        reverse_layout.addWidget(self.reverse_note)
        self.shell_label, self.shell_edit, self.shell_btn = self.add_reverse_row(reverse_layout)
        self.shell_btn.clicked.connect(self.choose_shell)
        self.shell_edit.textChanged.connect(
            lambda value: self.reverse_field_changed('shell', value))
        self.raster_checkbox = QCheckBox()
        self.raster_checkbox.toggled.connect(
            lambda checked: self.reverse_field_changed('graphic_mode',
                                                        'png' if checked else 'native'))
        reverse_layout.addWidget(self.raster_checkbox)
        self.reverse_panel.hide()
        self.project_page.details_layout.addWidget(self.reverse_panel)

        info = QVBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName('status')
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        info.addWidget(self.status_label)
        info.addWidget(self.progress)
        self.project_page.footer_layout.addLayout(info, 1)
        self.open_btn = QPushButton()
        self.open_btn.clicked.connect(self.open_selected_folder)
        self.open_btn.setEnabled(False)
        self.project_page.footer_layout.addWidget(self.open_btn)
        self.run_btn = QPushButton()
        self.run_btn.setObjectName('primary')
        self.run_btn.clicked.connect(self.start_queue)
        self.project_page.footer_layout.addWidget(self.run_btn)
        self.footnote_label = self.project_page.footnote_label
        self.footnote_label.show()
        self.premiere_tabs.addTab(self.project_page, '')
        self.shortcut_panel = ShortcutConverterPanel(self.premiere_tabs, self.language)
        self.premiere_tabs.addTab(self.shortcut_panel, '')

        self.planned_features: list[tuple[QTabWidget, PlannedFeature, str]] = []
        self.add_planned_feature(self.premiere_tabs, 'Premiere Pro ↔ FilmCraft', 'plugins')
        self.add_planned_feature(self.after_effects_tabs, 'After Effects ↔ EffectCraft', 'projects')
        self.add_planned_feature(self.after_effects_tabs, 'After Effects ↔ EffectCraft', 'hotkeys')
        self.plugin_panel = AexConverterPanel(self.after_effects_tabs, self.language)
        self.after_effects_tabs.addTab(self.plugin_panel, '')
        for feature in ('projects', 'hotkeys', 'plugins'):
            self.add_planned_feature(self.photoshop_tabs, 'Photoshop ↔ PhotoCraft', feature)
        # Switching to After Effects opens the implemented plug-in page, not a placeholder.
        self.after_effects_tabs.setCurrentIndex(2)

        self.apply_theme()
        self.retranslate()
        self.refresh()

    def add_planned_feature(self, tabs: QTabWidget, program: str, feature: str):
        placeholder = PlannedFeature(program, feature, self.language)
        tabs.addTab(placeholder, '')
        self.planned_features.append((tabs, placeholder, feature))

    @staticmethod
    def add_reverse_row(layout):
        row = QHBoxLayout()
        label = QLabel()
        label.setMinimumWidth(160)
        edit = QLineEdit()
        button = QPushButton()
        row.addWidget(label)
        row.addWidget(edit, 1)
        row.addWidget(button)
        layout.addLayout(row)
        return label, edit, button

    def t(self, key, **values):
        return tr(self.language, key, **values)

    def language_changed(self, index):
        lang = self.language_combo.itemData(index)
        if lang not in ('ru', 'en') or lang == self.language:
            return
        self.language = lang
        self.settings.setValue('language', lang)
        self.retranslate()

    def retranslate(self):
        self.setWindowTitle(self.t('window_title'))
        self.language_combo.setItemText(0, 'Русский' if self.language == 'ru' else 'Russian')
        self.language_combo.setItemText(1, 'Английский' if self.language == 'ru' else 'English')
        self.header_title.setText(self.t('header_title').replace(
            '↔', '<span style="color:#647184">↔</span>'))
        self.subtitle_label.setText(self.t('subtitle'))
        self.local_tag.setText(self.t('local_app'))
        for tabs in (self.premiere_tabs, self.after_effects_tabs, self.photoshop_tabs):
            for index, feature in enumerate(('projects', 'hotkeys', 'plugins')):
                tabs.setTabText(index, self.t('tab_' + feature))
        for tabs, placeholder, feature in self.planned_features:
            placeholder.retranslate(self.language)
            index = tabs.indexOf(placeholder)
            tabs.setTabText(index, self.t('tab_' + feature) + self.t('planned_suffix'))
            tabs.setTabToolTip(index, self.t('planned_tooltip',
                                            feature=self.t('tab_' + feature),
                                            pair=placeholder.program))
        self.shortcut_panel.language = self.language
        self.shortcut_panel.retranslate()
        self.plugin_panel.language = self.language
        self.plugin_panel.retranslate()
        self.project_page.title_label.setText(self.t('project_heading'))
        self.project_page.note_label.setText(self.t('project_note'))
        self.project_page.source_title.setText(self.t('source_projects'))
        self.drop.language = self.language
        self.drop.retranslate()
        self.add_btn.setText(self.t('add'))
        self.remove_btn.setText(self.t('remove'))
        self.clear_btn.setText(self.t('clear'))
        self.output_title.setText(self.t('output_folder'))
        self.output_note.setText(self.t('configurable'))
        self.output_edit.setPlaceholderText(self.t('output_placeholder'))
        self.browse_btn.setText(self.t('browse'))
        self.queue_title.setText(self.t('queue'))
        self.table.setHorizontalHeaderLabels([
            self.t('project'), self.t('direction'), self.t('status'), self.t('result')])
        self.shell_label.setText(self.t('shell_label'))
        self.shell_edit.setPlaceholderText(self.t('shell_placeholder'))
        self.shell_btn.setText(self.t('browse'))
        self.reverse_note.setText(self.t('reverse_note'))
        self.raster_checkbox.setText(self.t('raster_checkbox'))
        self.open_btn.setText(self.t('open_folder'))
        self.run_btn.setText(self.t('convert_queue'))
        self.footnote_label.setText(self.t('footnote'))
        self.status_label.setText(self.t(self.last_status[0], **self.last_status[1]))
        self.refresh()

    def set_status(self, key, **values):
        self.last_status = (key, values)
        self.status_label.setText(self.t(key, **values))

    def apply_theme(self):
        self.setStyleSheet('''
            QWidget{background:#0d1118;color:#edf2f7;font-family:"Segoe UI",Arial,sans-serif;font-size:13px}
            QLabel#title{font-size:24px;font-weight:750;letter-spacing:-.4px;color:#f5f7fa}
            QLabel#formTitle{font-size:20px;font-weight:750;color:#f5f7fa}
            QLabel#muted,QLabel#footnote{color:#9aa6b5;font-size:12px}
            QTabWidget::pane{border:1px solid #2b3a47;border-radius:11px;background:#111720}
            QTabBar::tab{background:#171e29;color:#aab7c6;border:1px solid #344250;border-bottom:0;border-top-left-radius:9px;border-top-right-radius:9px;padding:10px 15px;margin-right:3px;font-weight:700}
            QTabBar::tab:selected{color:#90e9c8;background:#22372f;border-color:#54a98c}
            QTabBar::tab:hover:!selected{color:#e5f0ed;background:#273340}
            QLabel#tag{color:#9cebd2;background:#152721;border:1px solid #315a4e;border-radius:10px;padding:7px 10px;font-size:10px;font-weight:750;letter-spacing:.6px}
            QLabel#section{font-size:11px;font-weight:800;letter-spacing:1px;color:#b8c4d2}
            QFrame#dropArea{background:#131a23;border:2px dashed #435063;border-radius:16px}
            QFrame#dropArea[dragging="true"]{background:#142920;border-color:#72e1bd}
            QLabel#dropIcon{font-size:27px;color:#74e3bf;background:#1d342e;border-radius:17px;min-width:48px;max-width:48px;min-height:46px;max-height:46px}
            QLabel#dropTitle{font-size:16px;font-weight:700;color:#f0f5f8}
            QFrame#panel{background:#141a23;border:1px solid #2b3442;border-radius:13px}
            QLineEdit{background:#0a0e14;border:1px solid #343f4e;border-radius:8px;padding:10px 11px;color:#e9eef4;selection-background-color:#3a8f78}
            QLineEdit:focus{border-color:#69d5b4}
            QPushButton{background:#1b232e;border:1px solid #394555;border-radius:9px;padding:9px 13px;color:#e2e8ef;font-weight:650}
            QPushButton:hover{background:#252f3c;border-color:#596a7c}
            QPushButton:disabled{color:#697483;background:#171c24;border-color:#252b35}
            QPushButton#primary{background:#71e0bd;border-color:#71e0bd;color:#08271d;font-weight:800;padding:11px 16px}
            QPushButton#primary:hover{background:#93efd2}
            QTableWidget{background:#111720;border:1px solid #2a3340;border-radius:11px;gridline-color:#252d38;alternate-background-color:#141b25;selection-background-color:#20372f;selection-color:#fff}
            QHeaderView::section{background:#171e28;color:#98a6b6;border:0;border-bottom:1px solid #303a48;padding:9px;font-size:11px;font-weight:750}
            QTableWidget::item{padding:7px;border-bottom:1px solid #222a34}
            QProgressBar{border:0;background:#202833;border-radius:3px}
            QProgressBar::chunk{background:#70dfbc;border-radius:3px}
            QLabel#status{font-size:12px;color:#b8c4d2}
        ''')

    def add_paths(self, paths):
        if self.busy:
            return
        added = []
        rejected = []
        known = {os.path.normcase(os.path.realpath(rec['path'])) for rec in self.files}
        for raw in paths:
            path = Path(raw)
            key = os.path.normcase(os.path.realpath(str(path)))
            if key in known:
                continue
            try:
                direction = detect_project_direction(path)
            except ProjectTypeError as exc:
                rejected.append(f'{path.name}: {self.t("invalid_" + exc.code)}')
                continue
            except OSError as exc:
                rejected.append(f'{path.name}: {exc}')
                continue
            self.files.append({
                'path': str(path), 'direction': direction,
                'shell': '', 'graphic_mode': 'native', 'state': 'pending',
                'output': '', 'error': '',
            })
            added.append(len(self.files) - 1)
            known.add(key)
        if added:
            self.set_status('added', n=len(added))
        self.refresh()
        # Show the per-project settings immediately when a new FC file is added.
        selected = next((i for i in added if self.files[i]['direction'] == FC_TO_PR),
                        added[0] if added else None)
        if selected is not None:
            self.table.setCurrentCell(selected, 0)
        if rejected:
            lines = rejected[:10]
            if len(rejected) > 10:
                lines.append(self.t('invalid_more', n=len(rejected) - 10))
            QMessageBox.warning(self, self.t('invalid_title'),
                                self.t('invalid_header') + '\n' + '\n'.join(lines))

    def choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, self.t('add_dialog'), '', self.t('project_filter'))
        if paths:
            self.add_paths(paths)

    def choose_output_dir(self):
        current = self.output_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, self.t('output_dialog'), current)
        if path:
            self.output_edit.setText(path)
            self.settings.setValue('output_dir', path)

    def selected_fc_record(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.files) and self.files[row]['direction'] == FC_TO_PR:
            return self.files[row]
        return None

    def choose_shell(self):
        if self.selected_fc_record() is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.t('choose_shell_project'),
            self.shell_edit.text().strip(), self.t('premiere_filter'))
        if path:
            self.shell_edit.setText(path)

    def update_reverse_panel(self, *args):
        record = self.selected_fc_record()
        self.reverse_panel.setVisible(record is not None)
        if record is None:
            return
        self.reverse_heading.setText(self.t('reverse_heading', name=Path(record['path']).name))
        self._loading_reverse = True
        try:
            for field, edit in (('shell', self.shell_edit),):
                value = record.get(field, '')
                if edit.text() != value:
                    edit.setText(value)
            self.raster_checkbox.setChecked(record.get('graphic_mode') == 'png')
        finally:
            self._loading_reverse = False
        for widget in (self.shell_edit, self.shell_btn, self.raster_checkbox):
            widget.setEnabled(not self.busy)

    def reverse_field_changed(self, field, value):
        if self._loading_reverse or self.busy:
            return
        record = self.selected_fc_record()
        if record is None or record[field] == value:
            return
        record[field] = value
        if record['state'] != 'pending':
            record['state'] = 'pending'
            record['output'] = ''
            record['error'] = ''
        self.refresh()

    def remove_selected(self):
        if self.busy:
            return
        rows = sorted({item.row() for item in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.files):
                self.files.pop(row)
        self.refresh()

    def clear_queue(self):
        if self.busy:
            return
        self.files = []
        self.progress.setValue(0)
        self.set_status('queue_cleared')
        self.refresh()

    def refresh(self):
        selected = self.table.currentRow()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.files))
            for row, record in enumerate(self.files):
                name = Path(record['path']).name
                project = QTableWidgetItem(name)
                project.setToolTip(record['path'])
                self.table.setItem(row, 0, project)
                direction_key = 'dir_fc_pr' if record['direction'] == FC_TO_PR else 'dir_pr_fc'
                self.table.setItem(row, 1, QTableWidgetItem(self.t(direction_key)))
                state = record['state']
                state_key = {'pending': 'state_pending', 'running': 'state_running',
                             'done': 'state_done', 'error': 'state_error'}[state]
                status = QTableWidgetItem(self.t(state_key))
                if state == 'done':
                    status.setForeground(Qt.green)
                elif state == 'error':
                    status.setForeground(Qt.red)
                    status.setToolTip(record.get('error', ''))
                self.table.setItem(row, 2, status)
                result = record.get('error', '') if state == 'error' else ''
                result = result or (Path(record['output']).name if record.get('output') else self.t('dash'))
                out = QTableWidgetItem(result)
                out.setToolTip(record.get('error', '') or record.get('output', ''))
                self.table.setItem(row, 3, out)
        finally:
            self.table.blockSignals(False)
        if self.files:
            desired = selected if 0 <= selected < len(self.files) else 0
            if self.table.currentRow() != desired:
                self.table.setCurrentCell(desired, 0)
        n = len(self.files)
        if self.language == 'en':
            count_text = self.t('count_one' if n == 1 else 'count_projects', n=n)
        elif n == 0:
            count_text = self.t('count_zero')
        elif n % 10 == 1 and n % 100 != 11:
            count_text = self.t('count_one', n=n)
        elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            count_text = self.t('count_few', n=n)
        else:
            count_text = self.t('count_projects', n=n)
        self.count_label.setText(count_text)
        self.run_btn.setEnabled(not self.busy and any(
            record['state'] in ('pending', 'error') for record in self.files))
        for widget in (self.add_btn, self.remove_btn, self.clear_btn,
                       self.browse_btn, self.output_edit, self.drop):
            widget.setEnabled(not self.busy)
        self.table.setEnabled(not self.busy)
        row = self.table.currentRow()
        self.open_btn.setEnabled(not self.busy and 0 <= row < len(self.files)
                                 and bool(self.files[row].get('output')))
        self.update_reverse_panel()

    def start_queue(self):
        if self.busy:
            return
        pending = [(i, record.copy()) for i, record in enumerate(self.files)
                   if record['state'] in ('pending', 'error')]
        if not pending:
            return
        records = []
        missing = []
        for index, record in pending:
            error = ''
            if record['direction'] == FC_TO_PR:
                name = Path(record['path']).name
                value = (record.get('shell') or '').strip()
                if value and not Path(value).is_file():
                    error = self.t('no_shell', name=name)
            if error:
                self.files[index].update(state='error', error=error, output='')
                missing.append((index, error))
            else:
                records.append((index, record))
        if missing:
            self.refresh()
            self.table.setCurrentCell(missing[0][0], 0)
            QMessageBox.warning(self, self.t('templates_needed_title'),
                                self.t('templates_needed',
                                       details='\n'.join(message for _, message in missing)))
        if not records:
            return
        directory = Path(os.path.expanduser(
            self.output_edit.text().strip() or str(Path.home() / 'Converted Projects'))).resolve()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, self.t('folder_error_title'), str(exc))
            return
        self.settings.setValue('output_dir', str(directory))
        self.output_edit.setText(str(directory))
        self.busy = True
        self.progress.setRange(0, len(records))
        self.progress.setValue(0)
        self.completed = 0
        self.total = len(records)
        self.set_status('processing', done=0, total=self.total)
        self.worker = ConversionWorker(records, directory, self.language)
        self.worker.fileStarted.connect(self.file_started)
        self.worker.fileSucceeded.connect(self.file_succeeded)
        self.worker.fileFailed.connect(self.file_failed)
        self.worker.queueFinished.connect(self.queue_finished)
        self.refresh()
        self.worker.start()

    def file_started(self, index):
        self.files[index]['state'] = 'running'
        self.files[index]['output'] = ''
        self.files[index]['error'] = ''
        self.set_status('converting', name=Path(self.files[index]['path']).name)
        self.refresh()

    def file_succeeded(self, index, path, messages):
        record = self.files[index]
        record['state'] = 'done'
        record['output'] = path
        record['error'] = ''
        self.completed += 1
        self.progress.setValue(self.completed)
        if messages:
            self.set_status('done_warnings', name=Path(path).name, n=messages)
        else:
            self.set_status('done', name=Path(path).name)
        self.refresh()

    def file_failed(self, index, error, output):
        record = self.files[index]
        record['state'] = 'error'
        record['error'] = self.t('report_write_failed', error=error) if output else error
        record['output'] = output
        self.completed += 1
        self.progress.setValue(self.completed)
        self.set_status('failed', name=Path(record['path']).name)
        self.refresh()

    def queue_finished(self):
        if self.worker:
            self.worker.wait()
            self.worker = None
        self.busy = False
        self.set_status('queue_finished')
        self.refresh()

    def open_selected_folder(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.files) and self.files[row].get('output'):
            QDesktopServices.openUrl(QUrl.fromLocalFile(
                str(Path(self.files[row]['output']).parent)))

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, self.t('close_running_title'),
                                    self.t('close_running_text'))
            event.ignore()
            return
        event.accept()


def main():
    app=QApplication(sys.argv);app.setApplicationName(APP_NAME);app.setOrganizationName('FilmCraftTools')
    window=MainWindow();window.show();sys.exit(app.exec())

if __name__=='__main__':main()
