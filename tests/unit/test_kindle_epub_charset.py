"""Charset repair must preserve EPUB XHTML well-formedness, including .html files."""
import ast
from pathlib import Path
import re
from typing import Optional
import unittest
from xml.etree import ElementTree


def load_encoding_helpers():
    # Importing the command-line fixer acquires a global lock and configures its
    # service log. Exercise the actual pure helpers without those process effects.
    source = Path(__file__).resolve().parents[2] / 'scripts' / 'kindle_epub_fixer.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    fixer = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == 'EPUBFixer')
    names = {'_normalize_encoding_name', '_get_text_content', '_update_html_charset', 'fix_encoding'}
    methods = [node for node in fixer.body if isinstance(node, ast.FunctionDef)
               and node.name in names]
    namespace = {'re': re, 'Optional': Optional}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)
    return type('EncodingHelpers', (), {name: namespace[name] for name in names})


class TestKindleEpubCharset(unittest.TestCase):
    def repair(self, head):
        content = ('<?xml version="1.0" encoding="utf-8"?>'
                   '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                   '<title>Charset regression</title>' + head +
                   '</head><body><p>Café — original text</p></body></html>')
        ElementTree.fromstring(content)
        fixer = load_encoding_helpers()()
        # EPUB XHTML frequently uses .html rather than .xhtml in the ZIP.
        fixer.files = {'chapter.html': content}
        fixer.file_target_encodings = {'chapter.html': 'utf-8'}
        fixer.fixed_problems = []
        fixer.fix_encoding()
        output = fixer.files['chapter.html']
        root = ElementTree.fromstring(output)
        self.assertEqual(root.find('.//{http://www.w3.org/1999/xhtml}p').text,
                         'Café — original text')
        return root, output

    def test_inserted_charset_is_valid_xml_and_epub2_metadata(self):
        root, _ = self.repair('')
        meta = root.find('.//{http://www.w3.org/1999/xhtml}meta')
        self.assertEqual(meta.attrib, {'http-equiv': 'Content-Type',
                         'content': 'text/html; charset=utf-8'})

    def test_replaced_html5_charset_remains_well_formed(self):
        for meta in ['<meta charset="windows-1252" />', "<META CHARSET='iso-8859-1'/>"]:
            with self.subTest(meta=meta):
                root, _ = self.repair(meta)
                self.assertEqual(root.find('.//{http://www.w3.org/1999/xhtml}meta').get('content'),
                                 'text/html; charset=utf-8')

    def test_existing_content_type_keeps_its_other_attributes(self):
        root, _ = self.repair('<meta id="encoding" http-equiv="Content-Type" '
                              'content="text/html; charset=windows-1252" />')
        meta = root.find('.//{http://www.w3.org/1999/xhtml}meta')
        self.assertEqual(meta.get('id'), 'encoding')
        self.assertEqual(meta.get('content'), 'text/html; charset=utf-8')

    def test_second_pass_is_idempotent(self):
        _, output = self.repair('')
        fixer = load_encoding_helpers()()
        self.assertEqual(fixer._update_html_charset(output, 'utf-8'), output)


if __name__ == '__main__':
    unittest.main()
