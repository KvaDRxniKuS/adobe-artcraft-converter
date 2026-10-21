"""Embedded, neutral Premiere graph seed (not a user's project).

Adapted from `feature_linked_av_strict.prproj` in Tesseract-Converter:
https://github.com/mirage-hq/Tesseract-Converter/blob/main/crates/premiere_file/tests/fixtures/feature_linked_av_strict.prproj
Source (compressed) SHA-256: 5844a11b529b5f626a868f3ffcba3d11d75dfd2f78028c7da084478021e74f14
Changes: media paths, titles and source/sequence names replaced with placeholders;
XML reserialized and gzip compressed. The original work is MIT licensed:

MIT License

Copyright (c) tesseract-conv contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import base64
import gzip

# Kept in a .py module so existing source-only updaters and PyInstaller include it.
_SEED_GZIP_BASE64 = (
    "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"
    "TgEA"
)


def load_seed_xml() -> bytes:
    return gzip.decompress(base64.b64decode(_SEED_GZIP_BASE64))
