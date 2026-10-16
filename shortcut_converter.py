#!/usr/bin/env python3
"""Bidirectional Premiere Pro KYS <-> FilmCraft keyboard-shortcut converter.

Premiere's .kys files are XML. FilmCraft's keyboard-shortcut sets are JSON.
Only commands with a known crosswalk can be translated; all omissions and key
codes which cannot be represented are listed in a sibling conversion report.
"""
from __future__ import annotations
import argparse, json, re, sys, xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

FC_FORMAT = 'filmcraft-keyboard-shortcuts'

MESSAGES = {
 'ru': {
  'not_fc':'Не похоже на FilmCraft keyboard-shortcuts JSON.','empty_keys':'Пустая комбинация клавиш',
  'missing_primary':'Не указан основной клавишный символ: {value}','unsupported_key':'Клавиша пока не поддержана: {key}',
  'bad_vk':'Некорректный KYS virtualkey: {code}','bad_nonprintable':'Неподдерживаемый KYS virtualkey: {code}',
  'unknown_vk':'Неизвестный Premiere virtualkey {code}','bad_template':'Шаблон JSON не является FilmCraft shortcuts JSON.',
  'missing_shortcuts':'В KYS отсутствует узел <shortcuts>.','unmapped_fc':'Без соответствия FilmCraft: {context} / {command}',
  'transfer_error':'{command}: {error}','kys_template_missing':'В KYS-шаблоне отсутствует узел <shortcuts>.',
  'unmapped_premiere':'Без соответствия Premiere: {command}{panel}','missing_context':'В KYS-шаблоне нет контекста {context} для {command}',
  'missing_command':'В KYS-шаблоне нет команды {command}; пропущена {fc_command}',
  'duplicate_target':'Команды FilmCraft «{first}» и «{second}» сопоставлены одной Premiere-команде {context} / {command}; оставлена первая.',
  'kys_summary':'Перенесено назначений: {count}. Назначения неподдерживаемых команд не перенесены.',
  'fc_summary':'Перенесено назначений: {count}. Неизвестные FilmCraft-команды оставлены только в отчёте.',
  'need_fc_template':'Для KYS укажите --fc-template <FilmCraft shortcuts .json>.',
  'need_kys_template':'Для FC JSON укажите --kys-template <Premiere .kys>.',
  'bad_input':'Вход должен быть .kys/.kys.txt или FilmCraft shortcuts .json.',
  'report':'Отчёт конвертации горячих клавиш','input':'Вход','output':'Выход','result':'Результат'
 },
 'en': {
  'not_fc':'This does not look like FilmCraft keyboard-shortcuts JSON.','empty_keys':'Empty key combination',
  'missing_primary':'No primary key specified: {value}','unsupported_key':'Unsupported key: {key}',
  'bad_vk':'Invalid KYS virtualkey: {code}','bad_nonprintable':'Unsupported non-printable KYS virtualkey: {code}',
  'unknown_vk':'Unknown Premiere virtualkey {code}','bad_template':'The JSON template is not a FilmCraft shortcuts JSON file.',
  'missing_shortcuts':'The KYS file has no <shortcuts> node.','unmapped_fc':'No FilmCraft mapping for: {context} / {command}',
  'transfer_error':'{command}: {error}','kys_template_missing':'The KYS template has no <shortcuts> node.',
  'unmapped_premiere':'No Premiere mapping for: {command}{panel}','missing_context':'KYS template has no context {context} for {command}',
  'missing_command':'KYS template has no command {command}; skipped {fc_command}',
  'duplicate_target':'FilmCraft commands “{first}” and “{second}” map to the same Premiere command {context} / {command}; kept the first.',
  'kys_summary':'Transferred {count} assignments. Assignments for unsupported commands were not transferred.',
  'fc_summary':'Transferred {count} assignments. Unmapped FilmCraft commands are listed in the report.',
  'need_fc_template':'Specify --fc-template <FilmCraft shortcuts .json> for KYS input.',
  'need_kys_template':'Specify --kys-template <Premiere .kys> for FilmCraft JSON input.',
  'bad_input':'Input must be .kys/.kys.txt or FilmCraft shortcuts .json.',
  'report':'Keyboard shortcut conversion report','input':'Input','output':'Output','result':'Result'
 }
}

def msg(language: str, key: str, **values) -> str:
    lang = 'en' if language == 'en' else 'ru'
    return MESSAGES[lang][key].format(**values)

# (FilmCraft command, panel) -> (Premiere context, commandname).
# Unlisted commands are intentionally not guessed: command IDs often look
# similar while doing different things in the two applications.
ALIASES = {
    ('tool.selection', None): ('context.global', 'cmd.tools.01pointer'),
    ('tool.trackSelectBackward', None): ('context.global', 'cmd.tools.02_5trackselectbackward'),
    ('tool.trackSelectForward', None): ('context.global', 'cmd.tools.02trackselectforward'),
    ('tool.ripple', None): ('context.global', 'cmd.tools.03ripple'),
    ('tool.rolling', None): ('context.global', 'cmd.tools.04roll'),
    ('tool.rateStretch', None): ('context.global', 'cmd.tools.05ratestretch'),
    ('tool.razor', None): ('context.global', 'cmd.tools.06razor'),
    ('tool.slip', None): ('context.global', 'cmd.tools.07slip'),
    ('tool.slide', None): ('context.global', 'cmd.tools.08slide'),
    ('tool.pen', None): ('context.global', 'cmd.tools.09pen'),
    ('tool.hand', None): ('context.global', 'cmd.tools.10hand'),
    ('tool.zoom', None): ('context.global', 'cmd.tools.11zoom'),
    ('tool.type', None): ('context.global', 'cmd.tools.12text'),
    ('app.keyboardShortcuts', None): ('context.global', 'cmd.edit.keyboardshortcuts'),
    ('app.settings.general', None): ('context.global', 'cmd.project.settings.general'),
    ('app.quit', None): ('context.global', 'cmd.file.exit'),
    ('file.open', None): ('context.global', 'cmd.file.openproject'),
    ('file.importFromMediaBrowser', None): ('context.global', 'cmd.file.importfrombrowser'),
    ('file.mediaProperties', None): ('context.global', 'cmd.file.properties.file'),
    ('mode.export', None): ('context.global', 'cmd.file.export.movie'),
    ('export.queue.add', None): ('context.global', 'cmd.file.export.sendtoqueue'),
    ('file.exportFrame', None): ('context.global', 'cmd.export.frame'),
    ('clip.audioChannels', None): ('context.global', 'cmd.clip.audiooptions.sourcechannelmappings'),
    ('clip.audioGain', None): ('context.global', 'cmd.clip.audiooptions.gain'),
    ('clip.speedDuration', None): ('context.global', 'cmd.clip.speed'),
    ('clip.link', None): ('context.global', 'cmd.clip.linkaudioandvideo'),
    ('clip.setPosterFrame', None): ('context.global', 'cmd.posterframe.set'),
    ('clip.clearPosterFrame', None): ('context.global', 'cmd.posterframe.clear'),
    ('clip.volumeUp', None): ('context.global', 'cmd.clip.audiooptions.nudgevolumeup'),
    ('clip.volumeDown', None): ('context.global', 'cmd.clip.audiooptions.nudgevolumedown'),
    ('clip.volumeUpMany', None): ('context.global', 'cmd.sequence.increaseclipvolumemany'),
    ('clip.volumeDownMany', None): ('context.global', 'cmd.sequence.decreaseclipvolumemany'),
    ('sequence.addEdit', None): ('context.global', 'cmd.sequence.razorateditline'),
    ('sequence.addEditAllTracks', None): ('context.global', 'cmd.sequence.razorateditline.all'),
    ('sequence.applyVideoTransition', None): ('context.global', 'cmd.sequence.applydefaultvideotransition'),
    ('sequence.applyAudioTransition', None): ('context.global', 'cmd.sequence.applydefaultaudiotransition'),
    ('trim.applyDefaultTransition', None): ('context.global', 'cmd.sequence.applydefaulttransitions'),
    ('sequence.goToNextGap', None): ('context.global', 'cmd.sequence.findnextsequencegap'),
    ('sequence.goToPrevGap', None): ('context.global', 'cmd.sequence.findprevioussequencegap'),
    ('sequence.renderEffectsInToOut', None): ('context.global', 'cmd.sequence.preview'),
    ('source.insert', None): ('context.global', 'cmd.clip.insert'),
    ('source.overwrite', None): ('context.global', 'cmd.clip.overlay'),
    ('playback.toggle', None): ('context.global', 'cmd.transport.toggleplay'),
    ('playback.reverse', None): ('context.global', 'cmd.transport.shuttle.left'),
    ('playback.forward', None): ('context.global', 'cmd.transport.shuttle.right'),
    ('playback.stop', None): ('context.global', 'cmd.transport.shuttle.stop'),
    ('playback.slowReverse', None): ('context.global', 'cmd.transport.shuttle.slow.left'),
    ('playback.slowForward', None): ('context.global', 'cmd.transport.shuttle.slow.right'),
    ('playback.playAround', None): ('context.global', 'cmd.transport.playedit'),
    ('playback.inToOut', None): ('context.global', 'cmd.transport.playintoout'),
    ('playback.toOut', None): ('context.global', 'cmd.transport.play.ctitoout'),
    ('playhead.nextEdit', None): ('context.global', 'cmd.tlnav.next.edit'),
    ('playhead.prevEdit', None): ('context.global', 'cmd.tlnav.prev.edit'),
    ('playhead.nextEditAnyTrack', None): ('context.global', 'cmd.tlnav.next.edit.any.track'),
    ('playhead.prevEditAnyTrack', None): ('context.global', 'cmd.tlnav.prev.edit.any.track'),
    ('playhead.start', None): ('context.global', 'cmd.transport.sequence.start'),
    ('playhead.end', None): ('context.global', 'cmd.transport.sequence.end'),
    ('playhead.stepBack', None): ('context.global', 'cmd.transport.step.back'),
    ('playhead.stepBack5', None): ('context.global', 'cmd.transport.step.back.five'),
    ('playhead.stepForward', None): ('context.global', 'cmd.transport.step.forward'),
    ('playhead.stepForward5', None): ('context.global', 'cmd.transport.step.forward.five'),
    ('markers.markIn', None): ('context.global', 'cmd.common.setin'),
    ('markers.markOut', None): ('context.global', 'cmd.common.setout'),
    ('markers.goToIn', None): ('context.global', 'cmd.goto.in'),
    ('markers.goToOut', None): ('context.global', 'cmd.goto.out'),
    ('markers.clearIn', None): ('context.global', 'cmd.clear.in'),
    ('markers.clearOut', None): ('context.global', 'cmd.clear.out'),
    ('markers.clearInOut', None): ('context.global', 'cmd.clear.inandout'),
    ('markers.add', None): ('context.global', 'cmd.set.marker'),
    ('markers.goNext', None): ('context.global', 'cmd.marker.gotomarker.next'),
    ('markers.goPrev', None): ('context.global', 'cmd.marker.gotomarker.previous'),
    ('markers.clearCurrent', None): ('context.global', 'cmd.marker.clearmarker.current'),
    ('markers.clearAll', None): ('context.global', 'cmd.marker.clearmarker.all'),
    ('graphics.newText', None): ('context.global', 'cmd.graphics.add.text'),
    ('graphics.newRectangle', None): ('context.global', 'cmd.graphics.add.shape.rectangle'),
    ('graphics.newEllipse', None): ('context.global', 'cmd.graphics.add.shape.ellipse'),
    ('graphics.beginTextEditing', None): ('context.global', 'cmd.graphics.enter.text.edit'),
    ('graphics.selectNextLayer', None): ('context.global', 'cmd.graphics.select.next.graphic.layer'),
    ('graphics.selectPreviousLayer', None): ('context.global', 'cmd.graphics.select.previous.graphic.layer'),
    ('graphics.alignTextCenter', None): ('context.global', 'cmd.graphicsinspector.aligncenter'),
    ('graphics.alignTextRight', None): ('context.global', 'cmd.graphicsinspector.alignright'),
    ('graphics.alignTextLeft', None): ('context.global', 'cmd.graphicsinspector.alignleft'),
    ('graphics.nudgeLeft', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.left.one'),
    ('graphics.nudgeLeft5', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.left.five'),
    ('graphics.nudgeRight', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.right.one'),
    ('graphics.nudgeRight5', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.right.five'),
    ('graphics.nudgeUp', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.up.one'),
    ('graphics.nudgeUp5', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.up.five'),
    ('graphics.nudgeDown', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.down.one'),
    ('graphics.nudgeDown5', 'Program'): ('context.Graphics', 'cmd.monitor.nudge.down.five'),
    ('edit.clear', 'Program'): ('context.Graphics', 'cmd.graphics.clear'),
    ('edit.rippleDelete', 'Timeline'): ('context.timeline', 'cmd.timeline.ripple.delete'),
    ('window.nextPanel', None): ('context.global', 'cmd.select.next.panel'),
    ('window.prevPanel', None): ('context.global', 'cmd.select.previous.panel'),
    ('window.openSearch', None): ('context.global', 'cmd.searchwindow.open'),
    ('panel.selectFindBox', None): ('context.global', 'cmd.select.find.box'),
    ('sequence.revealNested', None): ('context.global', 'cmd.tlnav.reveal.nested.sequence'),
    ('graphics.bringForward', None): ('context.global', 'cmd.graphics.move.graphic.layer.up'),
    ('graphics.bringToFront', None): ('context.global', 'cmd.graphics.move.graphic.layer.to.top'),
    ('graphics.sendBackward', None): ('context.global', 'cmd.graphics.move.graphic.layer.down'),
    ('graphics.sendToBack', None): ('context.global', 'cmd.graphics.move.graphic.layer.to.bottom'),
    ('view.showRulers', 'Program'): ('context.program.monitor', 'cmd.monitor.rulers'),
    ('view.showGuides', 'Program'): ('context.program.monitor', 'cmd.monitor.guides'),
    ('view.lockGuides', 'Program'): ('context.program.monitor', 'cmd.monitor.lockguides'),
    ('view.snapInProgramMonitor', 'Program'): ('context.program.monitor', 'cmd.monitor.snapping'),
    ('timeline.selectClipAtPlayhead', None): ('context.global', 'cmd.tlnav.select.clip.at.playhead'),
    ('timeline.selectNextClip', None): ('context.global', 'cmd.tlnav.select.next.clip'),
    ('timeline.selectPrevClip', None): ('context.global', 'cmd.tlnav.select.previous.clip'),
    ('timeline.toggleAllSourceAudio', None): ('context.global', 'cmd.tlnav.toggle.all.source.audio'),
    ('timeline.toggleAllSourceVideo', None): ('context.global', 'cmd.tlnav.toggle.all.source.video'),
    ('timeline.nudgeLeft', 'Timeline'): ('context.timeline', 'cmd.timeline.nudge.left.one'),
    ('timeline.nudgeRight', 'Timeline'): ('context.timeline', 'cmd.timeline.nudge.right.one'),
    ('timeline.nudgeLeft5', 'Timeline'): ('context.timeline', 'cmd.timeline.nudge.left.several'),
    ('timeline.nudgeRight5', 'Timeline'): ('context.timeline', 'cmd.timeline.nudge.right.several'),
    ('timeline.nudgeUp', 'Timeline'): ('context.timeline', 'cmd.timeline.nudge.up'),
    ('timeline.nudgeDown', 'Timeline'): ('context.timeline', 'cmd.timeline.nudge.down'),
    ('timeline.slipLeft', 'Timeline'): ('context.timeline', 'cmd.timeline.slip.left.one'),
    ('timeline.slipRight', 'Timeline'): ('context.timeline', 'cmd.timeline.slip.right.one'),
    ('timeline.slipLeft5', 'Timeline'): ('context.timeline', 'cmd.timeline.slip.left.several'),
    ('timeline.slipRight5', 'Timeline'): ('context.timeline', 'cmd.timeline.slip.right.several'),
    ('timeline.slideLeft', 'Timeline'): ('context.timeline', 'cmd.timeline.slide.left.one'),
    ('timeline.slideRight', 'Timeline'): ('context.timeline', 'cmd.timeline.slide.right.one'),
    ('timeline.slideLeft5', 'Timeline'): ('context.timeline', 'cmd.timeline.slide.left.several'),
    ('timeline.slideRight5', 'Timeline'): ('context.timeline', 'cmd.timeline.slide.right.several'),
    ('timeline.increaseVideoHeight', 'Timeline'): ('context.timeline', 'cmd.timeline.increase.video.tracks.height'),
    ('timeline.decreaseVideoHeight', 'Timeline'): ('context.timeline', 'cmd.timeline.decrease.video.tracks.height'),
    ('timeline.increaseAudioHeight', 'Timeline'): ('context.timeline', 'cmd.timeline.increase.audio.tracks.height'),
    ('timeline.decreaseAudioHeight', 'Timeline'): ('context.timeline', 'cmd.timeline.decrease.audio.tracks.height'),
    ('timeline.nextScreen', 'Timeline'): ('context.timeline', 'cmd.timeline.show.next.screen'),
    ('timeline.prevScreen', 'Timeline'): ('context.timeline', 'cmd.timeline.show.previous.screen'),
    ('trim.extendToPlayhead', None): ('context.global', 'cmd.sequence.extendselectededittoplayhead'),
    ('trim.extendNextEdit', None): ('context.global', 'cmd.sequence.extendnextedittoplayhead'),
    ('trim.extendPreviousEdit', None): ('context.global', 'cmd.sequence.extendpreviousedittoplayhead'),
    ('trim.backward', None): ('context.global', 'cmd.sequence.trimbackward'),
    ('trim.backwardMany', None): ('context.global', 'cmd.sequence.trimbackwardmany'),
    ('trim.forward', None): ('context.global', 'cmd.sequence.trimforward'),
    ('trim.forwardMany', None): ('context.global', 'cmd.sequence.trimforwardmany'),
    ('trim.rippleNext', None): ('context.global', 'cmd.sequence.rippletrimnextedittoplayhead'),
    ('trim.ripplePrevious', None): ('context.global', 'cmd.sequence.rippletrimpreviousedittoplayhead'),
    ('trim.edit', None): ('context.global', 'cmd.sequence.toggletrimtype'),
    ('file.newBinFromSelection', 'Project'): ('context.project', 'cmd.file.newbinfromselection'),
    ('file.newBin', 'Project'): ('context.project', 'cmd.file.new.bin'),
    ('project.delete', 'Project'): ('context.project', 'cmd.project.deletewithoptions'),
    ('source.open', 'Project'): ('context.project', 'cmd.file.openinclipmode'),
    ('edit.clear', 'Timeline'): ('context.timeline', 'cmd.edit.clear'),
    ('edit.clear', 'Properties'): ('context.Properties2', 'cmd.graphics.clear'),
    ('edit.paste', 'Timeline'): ('context.timeline', 'cmd.edit.paste'),
    ('edit.pasteInsert', 'Timeline'): ('context.timeline', 'cmd.edit.pasteinsert'),
    ('edit.undo', 'History'): ('context.history', 'cmd.history.step.backward'),
    ('edit.redo', 'History'): ('context.history', 'cmd.history.step.forward'),
    ('playback.toggle', 'Metadata'): ('context.metadata_editor', 'cmd.transport.toggleplay'),
    ('playback.loop', 'Audio Track Mixer'): ('context.audiomixer', 'cmd.monitor.loop'),
    ('playback.loop', 'Metadata'): ('context.metadata_editor', 'cmd.monitor.loop'),
    ('captions.newTrack', None): ('context.global', 'cmd.caption.add.track'),
    ('captions.add', None): ('context.global', 'cmd.caption.add.trackitem'),
    ('projectPanel.hoverScrub', 'Project'): ('context.project', 'cmd.project.enablehover'),
    ('captions.merge', 'Text'): ('context.com.adobe.dva.text', 'cmd.caption.edit.merge'),
    ('captions.split', 'Text'): ('context.com.adobe.dva.text', 'cmd.caption.edit.split'),
    ('textPanel.prevWord', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.navigate.prev.word'),
    ('textPanel.nextWord', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.navigate.next.word'),
    ('textPanel.selectPrevWord', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.select.prev.word'),
    ('textPanel.selectNextWord', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.select.next.word'),
    ('textPanel.prevLine', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.navigate.prev.line'),
    ('textPanel.nextLine', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.navigate.next.line'),
    ('textPanel.selectPrevLine', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.select.prev.line'),
    ('textPanel.selectNextLine', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.select.next.line'),
    ('textPanel.segmentStart', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.navigate.segment.start'),
    ('textPanel.segmentEnd', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.navigate.segment.end'),
    ('textPanel.selectToSegmentStart', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.select.segment.start'),
    ('textPanel.selectToSegmentEnd', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.select.segment.end'),
    ('textPanel.delete', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.delete'),
    ('textPanel.rippleDelete', 'Text'): ('context.com.adobe.dva.text', 'cmd.text.ripple.delete'),
    ('mediaBrowser.openInSource', 'Media Browser'): ('context.mediabrowser', 'cmd.file.openinclipmode'),
}

# Context names used by Premiere KYS. Non-global contexts have an FC panel name.
KYS_TO_PANEL = {
    'context.project': 'Project', 'context.timeline': 'Timeline',
    'context.program.monitor': 'Program', 'context.source.monitor': 'Source',
    'context.effectcontrols': 'Effect Controls', 'context.Properties2': 'Properties',
    'context.com.adobe.dva.text': 'Text', 'context.history': 'History',
    'context.mediabrowser': 'Media Browser', 'context.audiomixer': 'Audio Track Mixer',
    'context.audioclipmixer': 'Audio Clip Mixer', 'context.metadata_editor': 'Metadata',
    'context.markerList': 'Markers', 'context.color': 'Color', 'context.Graphics': 'Program',
    'context.essentialsound': 'Essential Sound', 'context.search': 'Search',
}
PANEL_TO_CONTEXT = {v: k for k, v in KYS_TO_PANEL.items()}

# Windows-oriented Adobe virtual-key representation. Adobe uses the high bit
# plus an ASCII/virtual-key value for printable keys; selected older Adobe
# codes (Space and arrows) are normalized explicitly.
SPECIAL_TO_NAME = {
    1: 'Space', 2: 'Backspace', 4: 'Enter', 8: 'Backspace', 9: 'Tab',
    13: 'Enter', 27: 'Escape', 32: 'Space', 33: 'PageUp', 34: 'PageDown',
    35: 'End', 36: 'Home', 37: 'Left', 38: 'Up', 39: 'Right', 40: 'Down',
    42: 'Left', 43: 'Right', 44: 'Up', 45: 'Down', 46: 'Delete',
    112: 'F1', 113: 'F2', 114: 'F3', 115: 'F4', 116: 'F5', 117: 'F6',
    118: 'F7', 119: 'F8', 120: 'F9', 121: 'F10', 122: 'F11', 123: 'F12',
}
NAME_TO_SPECIAL = {v: k for k, v in SPECIAL_TO_NAME.items()}
# Prefer the Adobe key codes found in the supplied Premiere profile.
NAME_TO_SPECIAL.update({'Space': 1, 'Backspace': 2, 'Enter': 4, 'Left': 42, 'Right': 43, 'Up': 44, 'Down': 45})


def norm_command(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', s.lower().removeprefix('cmd.'))


def make_crosswalk(kys_root: ET.Element, fc_bindings: list[dict]) -> tuple[dict[tuple[str, str | None], tuple[str, str]], dict[tuple[str, str], tuple[str, str | None]]]:
    known_by_context: dict[str, list[str]] = defaultdict(list)
    for ctx in kys_root.findall('shortcuts/*'):
        for item in list(ctx):
            command=item.findtext('commandname')
            if command and command not in known_by_context[ctx.tag]: known_by_context[ctx.tag].append(command)
    fc_to_pr: dict[tuple[str, str | None], tuple[str, str]] = {
        key:value for key,value in ALIASES.items() if value[1] in known_by_context.get(value[0], [])
    }
    # Exact normalized-ID matches are safe (e.g. edit.undo <-> cmd.edit.undo).
    # Never fuzzy-match: similar IDs may describe different actions.
    for binding in fc_bindings:
        fc_cmd=binding.get('command'); panel=binding.get('panel')
        if not isinstance(fc_cmd,str): continue
        key=(fc_cmd,panel)
        if key in fc_to_pr: continue
        target_ctx='context.global' if panel is None else PANEL_TO_CONTEXT.get(panel)
        if target_ctx is None: continue
        matches=[cmd for cmd in known_by_context.get(target_ctx,[]) if norm_command(cmd)==norm_command(fc_cmd)]
        if len(matches)==1: fc_to_pr[key]=(target_ctx,matches[0])
    pr_to_fc: dict[tuple[str, str], tuple[str, str | None]] = {}
    for (fc_cmd, panel), (ctx, pr_cmd) in fc_to_pr.items():
        pr_to_fc.setdefault((ctx, pr_cmd), (fc_cmd, panel))
    return fc_to_pr, pr_to_fc


def all_bindings(obj: dict, language: str = 'ru') -> list[dict]:
    if obj.get('format') != FC_FORMAT or not isinstance(obj.get('bindings'), list):
        raise ValueError(msg(language, 'not_fc'))
    return obj['bindings']


def parse_fc_keys(value: str, platform: str = 'windows', language: str = 'ru') -> tuple[int, bool, bool, bool]:
    parts = [x.strip() for x in value.split('+') if x.strip()]
    if not parts:
        raise ValueError(msg(language, 'empty_keys'))
    ctrl = alt = shift = False
    key = None
    for part in parts:
        low = part.casefold()
        if low in ('cmd', 'command', 'ctrl', 'control'):
            ctrl = True
        elif low in ('alt', 'option'):
            alt = True
        elif low == 'shift':
            shift = True
        else:
            key = part
    if key is None:
        raise ValueError(msg(language, 'missing_primary', value=value))
    normalized = {'delete': 'Delete', 'backspace': 'Backspace', 'space': 'Space', 'enter': 'Enter', 'return': 'Enter', 'escape': 'Escape', 'esc': 'Escape', 'tab': 'Tab', 'home': 'Home', 'end': 'End', 'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down', 'pageup': 'PageUp', 'pagedown': 'PageDown'}
    key = normalized.get(key.casefold(), key)
    if key in NAME_TO_SPECIAL:
        vk = NAME_TO_SPECIAL[key]
    elif re.fullmatch(r'F(?:[1-9]|1[0-2])', key, re.I):
        vk = 111 + int(key[1:])
    elif len(key) == 1 and key.isprintable():
        vk = 0x80000000 + ord(key.upper())
    else:
        raise ValueError(msg(language, 'unsupported_key', key=key))
    return vk, ctrl, alt, shift


def format_fc_keys(vk: str | int, ctrl: bool, alt: bool, shift: bool, language: str = 'ru') -> str:
    code = int(vk)
    if code >= 0x80000000:
        base = code & 0x7fffffff
        try:
            key = chr(base).upper()
        except ValueError as exc:
            raise ValueError(msg(language, 'bad_vk', code=code)) from exc
        if not key.isprintable(): raise ValueError(msg(language, 'bad_nonprintable', code=code))
    elif code in SPECIAL_TO_NAME:
        key = SPECIAL_TO_NAME[code]
    elif 48 <= code <= 57 or 65 <= code <= 90:
        key = chr(code)
    else:
        raise ValueError(msg(language, 'unknown_vk', code=code))
    parts=[]
    if ctrl: parts.append('Cmd')
    if alt: parts.append('Alt')
    if shift: parts.append('Shift')
    parts.append(key)
    return '+'.join(parts)


def load_fc_template(path: Path | None, language: str = 'ru') -> dict:
    if path:
        obj=json.loads(path.read_text(encoding='utf-8-sig'))
        if obj.get('format') != FC_FORMAT: raise ValueError(msg(language, 'bad_template'))
        return obj
    return {'format':FC_FORMAT,'version':1,'name':'FilmCraft Shortcuts','modified':True,'bindings':[]}


def convert_kys_to_fc(kys_path: Path, output: Path, fc_template: Path | None = None, language: str = 'ru') -> list[str]:
    root=ET.parse(kys_path).getroot()
    shortcuts=root.find('shortcuts')
    if shortcuts is None: raise ValueError(msg(language, 'missing_shortcuts'))
    template=load_fc_template(fc_template,language)
    bindings=all_bindings(template,language)
    fc_to_pr, _=make_crosswalk(root, bindings)
    mapped_fc=set(fc_to_pr)
    # Start from the FilmCraft preset, but clear bindings for commands whose
    # Premiere counterparts are represented; unshared FilmCraft commands stay intact.
    bindings[:]=[x for x in bindings if (x.get('command'),x.get('panel')) not in mapped_fc]
    existing={(x.get('command'),x.get('panel')):x for x in bindings}
    warnings=[]; converted=0
    for ctx in shortcuts:
        for item in ctx:
            pr_cmd=item.findtext('commandname')
            vk=item.findtext('virtualkey')
            if not pr_cmd or vk is None: continue
            target=next(((fc,panel) for (fc,panel),(c,cmd) in fc_to_pr.items() if c==ctx.tag and cmd==pr_cmd),None)
            if target is None:
                warnings.append(msg(language, 'unmapped_fc', context=ctx.tag, command=pr_cmd))
                continue
            fc_cmd,panel=target
            try:
                keys=format_fc_keys(vk,item.findtext('modifier.ctrl','false')=='true',item.findtext('modifier.alt','false')=='true',item.findtext('modifier.shift','false')=='true',language)
            except ValueError as exc:
                warnings.append(msg(language, 'transfer_error', command=pr_cmd, error=exc))
                continue
            binding={'command':fc_cmd,'keys':keys}
            if panel: binding['panel']=panel
            key=(fc_cmd,panel)
            if key in existing:
                existing[key].update(binding)
            else:
                bindings.append(binding);existing[key]=binding
            converted+=1
    template['modified']=True
    template['name']=kys_path.stem
    output.write_text(json.dumps(template,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    warnings.insert(0,msg(language, 'kys_summary', count=converted))
    return warnings


def convert_fc_to_kys(fc_path: Path, output: Path, kys_template: Path, language: str = 'ru') -> list[str]:
    obj=json.loads(fc_path.read_text(encoding='utf-8-sig')); bindings=all_bindings(obj,language)
    tree=ET.parse(kys_template);root=tree.getroot();shortcuts=root.find('shortcuts')
    if shortcuts is None: raise ValueError(msg(language, 'kys_template_missing'))
    fc_to_pr,_=make_crosswalk(root, bindings)
    warnings=[];converted=0
    contexts={c.tag:c for c in shortcuts}
    applied_targets={}
    # Clear old KYS assignments for every mapped command in this FilmCraft set,
    # then apply the keys that are actually present in the JSON.
    targets=set(fc_to_pr.values())
    for (ctx_name,pr_cmd) in targets:
        ctx=contexts.get(ctx_name)
        if ctx is None: continue
        for item in ctx:
            if item.findtext('commandname')==pr_cmd:
                for tag in ('virtualkey','modifier.ctrl','modifier.alt','modifier.shift'):
                    child=item.find(tag)
                    if child is not None:item.remove(child)
    for binding in bindings:
        fc_cmd=binding.get('command');panel=binding.get('panel')
        spec=fc_to_pr.get((fc_cmd,panel)) or fc_to_pr.get((fc_cmd,None))
        if spec is None:
            warnings.append(msg(language, 'unmapped_premiere', command=fc_cmd, panel=f' [{panel}]' if panel else ''))
            continue
        ctx_name,pr_cmd=spec;ctx=contexts.get(ctx_name)
        if ctx is None:
            warnings.append(msg(language, 'missing_context', context=ctx_name, command=fc_cmd))
            continue
        item=next((x for x in ctx if x.findtext('commandname')==pr_cmd),None)
        if item is None:
            warnings.append(msg(language, 'missing_command', command=pr_cmd, fc_command=fc_cmd))
            continue
        target_key=(ctx_name,pr_cmd)
        if target_key in applied_targets:
            warnings.append(msg(language,'duplicate_target',first=applied_targets[target_key],second=fc_cmd,context=ctx_name,command=pr_cmd))
            continue
        try: vk,ctrl,alt,shift=parse_fc_keys(str(binding.get('keys','')),language=language)
        except ValueError as exc:
            warnings.append(msg(language, 'transfer_error', command=fc_cmd, error=exc))
            continue
        for tag,value in (('virtualkey',str(vk)),('modifier.ctrl',str(ctrl).lower()),('modifier.alt',str(alt).lower()),('modifier.shift',str(shift).lower())):
            child=item.find(tag)
            if child is None:child=ET.SubElement(item,tag)
            child.text=value
        applied_targets[target_key]=fc_cmd
        converted+=1
    output.write_bytes(ET.tostring(root,encoding='utf-8',xml_declaration=True))
    warnings.insert(0,msg(language, 'fc_summary', count=converted))
    return warnings


def main() -> int:
    ap=argparse.ArgumentParser(description='Convert shortcut sets between Premiere KYS XML and FilmCraft JSON')
    ap.add_argument('input',type=Path);ap.add_argument('output',type=Path,nargs='?')
    ap.add_argument('--kys-template',type=Path,help='Premiere KYS template used when input is FilmCraft JSON')
    ap.add_argument('--fc-template',type=Path,help='FilmCraft JSON template used when input is Premiere KYS')
    ap.add_argument('--language',choices=('ru','en'),default='ru',help='Language for messages and report')
    args=ap.parse_args();suffix=args.input.suffix.lower()
    if suffix=='.kys' or args.input.name.lower().endswith('.kys.txt'):
        default=args.input.with_suffix('.json') if suffix=='.kys' else args.input.with_name(args.input.name[:-len('.kys.txt')]+'.json')
        output=args.output or default
        if not args.fc_template: raise ValueError(msg(args.language, 'need_fc_template'))
        warnings=convert_kys_to_fc(args.input,output,args.fc_template,args.language)
    elif suffix=='.json':
        output=args.output or args.input.with_suffix('.kys')
        if not args.kys_template:raise ValueError(msg(args.language, 'need_kys_template'))
        warnings=convert_fc_to_kys(args.input,output,args.kys_template,args.language)
    else:raise ValueError(msg(args.language, 'bad_input'))
    report=output.with_name(output.stem+'_shortcuts_report.md')
    report.write_text(f'# {msg(args.language,"report")}\n\n- {msg(args.language,"input")}: `{args.input.name}`\n- {msg(args.language,"output")}: `{output.name}`\n\n## {msg(args.language,"result")}\n\n'+'\n'.join('- '+x for x in warnings)+'\n',encoding='utf-8')
    print(f'Created {output}\nCreated {report}\n'+warnings[0])
    if len(warnings)>1:print(f'Warnings: {len(warnings)-1}')
    return 0

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        print(f'Conversion failed: {exc}',file=sys.stderr);raise
