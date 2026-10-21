from __future__ import annotations

import unittest
from pathlib import Path

from src.services.content_library import ContentLibrary


class ContentLibraryTests(unittest.TestCase):
    def test_bundled_information_templates_load(self) -> None:
        library = ContentLibrary(Path(__file__).resolve().parents[1] / "content" / "server_content.json")
        library.reload()

        item = library.get("server-information")
        embed, view = library.make_message(item)

        self.assertEqual(embed.title, "Server Information")
        self.assertIsNone(view)
