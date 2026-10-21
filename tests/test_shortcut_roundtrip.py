"""Real mapped hotkey round-trip for the feature exposed in the new subtab."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from shortcut_converter import convert_fc_to_kys, convert_kys_to_fc

ROOT = Path(__file__).resolve().parents[1]


class ShortcutRoundTripTests(unittest.TestCase):
    def test_kys_json_kys_transfers_a_mapped_assignment(self):
        tree = ET.parse(ROOT / 'Premiere_Shortcuts_Template.kys')
        item = next(x for x in tree.getroot().iter()
                    if x.findtext('commandname') == 'cmd.tools.01pointer')
        ET.SubElement(item, 'virtualkey').text = str(0x80000000 + ord('V'))
        ET.SubElement(item, 'modifier.ctrl').text = 'true'
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            kys, fc, roundtrip = base / 'source.kys', base / 'output.json', base / 'roundtrip.kys'
            tree.write(kys, encoding='utf-8', xml_declaration=True)
            messages = convert_kys_to_fc(
                kys, fc, ROOT / 'FilmCraft_Shortcuts_Template.json', language='en')
            self.assertIn('Transferred 1 assignments', messages[0])
            obj = json.loads(fc.read_text(encoding='utf-8'))
            self.assertIn({'command': 'tool.selection', 'keys': 'Cmd+V'}, obj['bindings'])
            messages = convert_fc_to_kys(fc, roundtrip, ROOT / 'Premiere_Shortcuts_Template.kys',
                                         language='en')
            self.assertIn('Transferred 1 assignments', messages[0])
            restored = next(x for x in ET.parse(roundtrip).getroot().iter()
                            if x.findtext('commandname') == 'cmd.tools.01pointer')
            self.assertEqual(restored.findtext('virtualkey'), str(0x80000000 + ord('V')))
            self.assertEqual(restored.findtext('modifier.ctrl'), 'true')
            self.assertEqual(item.findtext('virtualkey'), str(0x80000000 + ord('V')))


if __name__ == '__main__':
    unittest.main()
