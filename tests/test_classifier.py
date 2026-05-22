import os
import sys
import types
import unittest

os.environ["OPENROUTER_API_KEY"] = "dummy"
os.environ["CLASSIFIER_MIN_DELAY"] = "0"
sys.modules.setdefault("httpx", types.SimpleNamespace(post=None))

import app.classifier as classifier


class _Response:
    status_code = 200

    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class ClassifierSanitizingTest(unittest.TestCase):
    def setUp(self):
        self._post = classifier.httpx.post
        self._known = classifier.get_known_groups
        classifier.get_known_groups = lambda: []

    def tearDown(self):
        classifier.httpx.post = self._post
        classifier.get_known_groups = self._known

    def _classify_with_response(self, title: str, response: str):
        classifier.httpx.post = lambda *args, **kwargs: _Response(response)
        return classifier.classify(title, "")

    def test_forbidden_cashback_uses_specific_ki_fallback(self):
        result = self._classify_with_response(
            "Google AI Pro 12 Monate mit Payback Cashback",
            "Cashback",
        )
        self.assertEqual(result, ["KI-Abo"])

    def test_product_corrections_override_common_wrong_labels(self):
        cases = [
            ("Gaming PC RTX 5070 Ryzen 7", "PC-Spiel", ["Gaming-PC"]),
            ("JBL Go Bluetooth Lautsprecher", "Bluetooth-Kopfhörer", ["Bluetooth-Lautsprecher"]),
            ("Akku Rasenmäher 36V", "Mähroboter", ["Rasenmäher"]),
            ("SUP-Pumpe elektrisch", "Luftreiniger", ["Luftpumpe"]),
        ]
        for title, response, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(self._classify_with_response(title, response), expected)

    def test_json_and_markdown_responses_are_tolerated(self):
        self.assertEqual(
            self._classify_with_response("LEGO Star Wars Set", '{"groups":["LEGO-Set"]}'),
            ["LEGO-Set"],
        )
        self.assertEqual(
            self._classify_with_response("Google AI Pro 12 Monate", "```\nKI-Abo\n```"),
            ["KI-Abo"],
        )


if __name__ == "__main__":
    unittest.main()
