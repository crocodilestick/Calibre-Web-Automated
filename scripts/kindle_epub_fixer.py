import zipfile
import os
import re
import xml.etree.ElementTree as ET

### Code adapted from https://github.com/innocenat/kindle-epub-fix
### Translated from Javascript to Python by community member tedderstar
### & modified and integrated into CWA by CrocodileStick

class EPUBFixer:
    def __init__(self, epub_path):
        self.epub_path = epub_path
        self.files = {}
        self.fixed_problems = []

    def read_epub(self):
        with zipfile.ZipFile(self.epub_path, 'r') as zip_ref:
            for file in zip_ref.namelist():
                ext = os.path.splitext(file)[1]
                if ext in ['.html', '.xhtml', '.xml', '.css', '.opf', '.ncx', '.svg']:
                    self.files[file] = zip_ref.read(file).decode('utf-8')
                else:
                    self.files[file] = zip_ref.read(file)

    def fix_encoding(self):
        encoding_declaration = '<?xml version="1.0" encoding="utf-8"?>'
        xml_declaration_pattern = re.compile(r'^<\?xml.*?\?>', re.IGNORECASE)

        for filename, content in self.files.items():
            if filename.endswith(('.html', '.xhtml')):
                if not xml_declaration_pattern.match(content):
                    self.files[filename] = f"{encoding_declaration}\n{content}"
                    self.fixed_problems.append(f"Fixed encoding for file {filename}")

    def fix_language(self):
        allowed_languages = {# ISO 639-1
                            'af', 'gsw', 'ar', 'eu', 'nb', 'br', 'ca', 'zh', 'kw', 'co', 'da', 'nl', 'stq', 'en', 'fi', 'fr', 'fy', 'gl',
                            'de', 'gu', 'hi', 'is', 'ga', 'it', 'ja', 'lb', 'mr', 'ml', 'gv', 'frr', 'nb', 'nn', 'pl', 'pt', 'oc', 'rm',
                            'sco', 'gd', 'es', 'sv', 'ta', 'cy',
                            # ISO 639-2
                            'afr', 'ara', 'eus', 'baq', 'nob', 'bre', 'cat', 'zho', 'chi', 'cor', 'cos', 'dan', 'nld', 'dut', 'eng', 'fin',
                            'fra', 'fre', 'fry', 'glg', 'deu', 'ger', 'guj', 'hin', 'isl', 'ice', 'gle', 'ita', 'jpn', 'ltz', 'mar', 'mal',
                            'glv', 'nor', 'nno', 'por', 'oci', 'roh', 'gla', 'spa', 'swe', 'tam', 'cym', 'wel'}
        opf_file = next((f for f in self.files if f.endswith('.opf')), None)

        if opf_file:
            root = ET.fromstring(self.files[opf_file])
            lang_tag = root.find(".//{http://purl.org/dc/elements/1.1/}language")

            current_lang = lang_tag.text if lang_tag is not None else 'undefined'

            if current_lang not in allowed_languages:
                new_lang = "en"  # Automatically set to 'en' for unsupported languages

                if lang_tag is None:
                    metadata = root.find(".//{http://www.idpf.org/2007/opf}metadata")
                    lang_tag = ET.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}language")
                lang_tag.text = new_lang

                self.files[opf_file] = ET.tostring(root, encoding='unicode')
                self.fixed_problems.append(f"Updated language from {current_lang} to {new_lang}")

    def fix_stray_images(self):
        img_tag_pattern = re.compile(r'<img([^>]*)>', re.IGNORECASE)
        src_pattern = re.compile(r'src\s*=\s*[\'"].+?[\'"]', re.IGNORECASE)

        for filename, content in self.files.items():
            if filename.endswith(('.html', '.xhtml')):
                original_content = content
                content = re.sub(
                    img_tag_pattern,
                    lambda match: '' if not src_pattern.search(match.group(1)) else match.group(0),
                    content
                )

                if content != original_content:
                    self.files[filename] = content
                    self.fixed_problems.append(f"Removed stray images in {filename}")

    def write_epub(self):
        with zipfile.ZipFile(self.epub_path, 'w') as zip_out:
            for filename, content in self.files.items():
                if isinstance(content, str):
                    zip_out.writestr(filename, content.encode('utf-8'))
                else:
                    zip_out.writestr(filename, content)

    def process(self):
        self.read_epub()
        self.fix_encoding()
        self.fix_language()
        self.fix_stray_images()
        self.write_epub()
        print("[cwa-kindle-epub-fixer] Processing completed.")
        if self.fixed_problems:
            print("[cwa-kindle-epub-fixer] \n".join(self.fixed_problems))
        else:
            print("[cwa-kindle-epub-fixer] No issues found!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("[cwa-kindle-epub-fixer] Usage: python epub_fixer.py <input_epub>")
        sys.exit(1)

    input_file = sys.argv[1]

    # Check if the input file is an EPUB file
    if not input_file.lower().endswith('.epub'):
        print("[cwa-kindle-epub-fixer] Error: The input file must be an EPUB file with a .epub extension.")
        sys.exit(1)

    EPUBFixer(input_file).process()