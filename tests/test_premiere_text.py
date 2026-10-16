"""Independent structural checks for Premiere 26 Source Text.

These checks read the public fixture layout and generated FlatBuffers. They do
NOT test whether Adobe Premiere opens, renders or permits editing the project.
"""
import base64
import struct
import unittest
import xml.etree.ElementTree as ET

from premiere_text import NativeTextUnsupported, create_native_text
from premiere_text_seed import load_text_seed_xml

try:
    import flatbuffers  # noqa: F401 - dependency for encoding only
except ImportError:
    flatbuffers = None


class TextView:
    def __init__(self, payload: bytes):
        length, magic = struct.unpack_from('<QI', payload)
        if length != len(payload) - 12 or magic != 0x11223344:
            raise ValueError('bad Source Text frame')
        self.buffer = payload[12:]

    def u32(self, pos):
        return struct.unpack_from('<I', self.buffer, pos)[0]

    def f32(self, pos):
        return struct.unpack_from('<f', self.buffer, pos)[0]

    def pointer(self, pos):
        return pos + self.u32(pos)

    def table(self, pos):
        vtable = pos - struct.unpack_from('<i', self.buffer, pos)[0]
        size = struct.unpack_from('<H', self.buffer, vtable)[0]
        return {slot: pos + struct.unpack_from('<H', self.buffer, vtable + 4 + slot * 2)[0]
                for slot in range((size - 4) // 2)
                if struct.unpack_from('<H', self.buffer, vtable + 4 + slot * 2)[0]}

    def vector(self, pos):
        start = self.pointer(pos)
        return [start + 4 + 4 * index for index in range(self.u32(start))]

    def string(self, pos):
        start = self.pointer(pos)
        return self.buffer[start + 4:start + 4 + self.u32(start)].decode('utf-8')

    def title(self):
        root = self.table(self.u32(0))
        doc = self.table(self.pointer(root[0]))
        run = self.table(self.pointer(self.vector(doc[0])[0]))
        style = self.table(self.pointer(run[1]))
        font = self.string(self.vector(doc[1])[0])
        text = self.string(run[0]).replace('\r', '\n')
        return doc, style, text, font


def sample_effect(text='Пример\nтитра', *, fill=None):
    def param(value, variant):
        return {'value': {variant: value}}
    return {'effect': 'graphic_text', 'enabled': True, 'params': {
        'text': param(text, 'Text'), 'font': param('Arial-BoldMT', 'Text'),
        'size': param(133., 'Float'), 'position': param({'x': 1720, 'y': 720}, 'Vec2'),
        'fill_color': param(fill or [1., .5, 0., 1.], 'Color'),
        'stroke': param(True, 'Bool'), 'stroke_color': param([0., 0., 0., 1.], 'Color'),
        'stroke_width': param(6., 'Float'),
    }}


class NativeTextPayloadTests(unittest.TestCase):
    def test_public_fixture_has_expected_schema_and_license(self):
        root = ET.fromstring(load_text_seed_xml())
        self.assertEqual(len(root), 34)
        self.assertEqual(len(root.findall('VideoClipTrackItem')), 1)
        self.assertEqual([node.findtext('MatchName') for node in root.findall('VideoFilterComponent')],
                         ['AE.ADBE Text'])
        node = root.find('ArbVideoComponentParam')
        self.assertIsNotNone(node)
        doc, style, text, font = TextView(
            base64.b64decode(node.findtext('StartKeyframeValue'))).title()
        self.assertEqual((text, font), ('py', 'Arial-BoldMT'))
        self.assertEqual(round(TextView(base64.b64decode(
            node.findtext('StartKeyframeValue'))).f32(style[1])), 160)
        self.assertEqual(set(doc), {0, 1, 26, 40, 43, 44})

    @unittest.skipIf(flatbuffers is None, 'flatbuffers is not installed')
    def test_utf8_fonts_style_color_and_normalized_position(self):
        result = create_native_text(sample_effect(), {'width': 3440, 'height': 1440},
                                    3440, 1440)
        view = TextView(result.payload)
        doc, style, text, font = view.title()
        self.assertEqual((text, font), ('Пример\nтитра', 'Arial-BoldMT'))
        self.assertAlmostEqual(view.f32(style[1]), 133.)
        fill = view.table(view.pointer(style[2]))
        self.assertEqual([view.buffer[fill[i]] for i in range(3)], [255, 128, 0])
        stroke = view.table(view.pointer(style[4]))
        self.assertEqual([view.buffer[stroke[i]] for i in range(3)], [0, 0, 0])
        self.assertEqual(view.buffer[style[5]], 1)
        self.assertAlmostEqual(view.f32(style[6]), 6.)
        self.assertEqual(set(doc), {0, 1, 26, 40, 43, 44})
        self.assertEqual(result.parameters[3], '0.5:0.5')
        self.assertEqual(result.parameters[9], '0:0')

    @unittest.skipIf(flatbuffers is None, 'flatbuffers is not installed')
    def test_no_fill_box_alignment_and_cyrillic_text(self):
        effect = sample_effect('Добрый день')
        effect['params']['fill'] = {'value': {'Bool': False}}
        effect['params']['box_width'] = {'value': {'Float': 400}}
        effect['params']['box_height'] = {'value': {'Float': 160}}
        effect['params']['align'] = {'value': {'Choice': 1}}
        effect['params']['caps'] = {'value': {'Choice': 2}}
        effect['params']['scale'] = {'value': {'Float': 90}}
        result = create_native_text(effect, {'width': 320, 'height': 180}, 1280, 720)
        view = TextView(result.payload)
        doc, style, text, _ = view.title()
        self.assertEqual(text, 'Добрый день')
        self.assertAlmostEqual(view.f32(doc[2]), 400.)
        self.assertAlmostEqual(view.f32(doc[3]), 160.)
        self.assertEqual(view.u32(doc[4]), 2)
        self.assertEqual(view.buffer[style[3]], 0)
        self.assertEqual(view.u32(style[12]), 2)
        self.assertEqual(result.parameters[4], '90.0')
        self.assertEqual(result.parameters[3], '5.375:4')

    def test_unsupported_style_and_animation_require_png(self):
        effect = sample_effect()
        effect['params']['shadow'] = {'value': {'Bool': True}}
        with self.assertRaisesRegex(NativeTextUnsupported, 'PNG'):
            create_native_text(effect, {'width': 320, 'height': 180}, 320, 180)
        effect['params']['shadow']['value']['Bool'] = False
        effect['params']['text']['keyframes'] = [{'time': 0}]
        with self.assertRaisesRegex(NativeTextUnsupported, 'Анимация'):
            create_native_text(effect, {'width': 320, 'height': 180}, 320, 180)
        del effect['params']['text']['keyframes']
        effect['params']['fill_color'] = {'value': {'Color': [1, .5, 0, .25]}}
        with self.assertRaisesRegex(NativeTextUnsupported, 'Прозрачность'):
            create_native_text(effect, {'width': 320, 'height': 180}, 320, 180)
