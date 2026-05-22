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


class _RateLimitedResponse:
    status_code = 429


class _UnauthorizedResponse:
    status_code = 401


class ClassifierSanitizingTest(unittest.TestCase):
    def setUp(self):
        self._post = classifier.httpx.post
        self._known = classifier.get_known_groups
        self._sleep = classifier.time.sleep
        classifier.get_known_groups = lambda: []
        classifier.time.sleep = lambda seconds: None
        classifier._remote_disabled_reason = None

    def tearDown(self):
        classifier.httpx.post = self._post
        classifier.get_known_groups = self._known
        classifier.time.sleep = self._sleep
        classifier._remote_disabled_reason = None

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

    def test_api_failures_use_local_fallback_instead_of_unclassified(self):
        classifier.httpx.post = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("401"))
        self.assertEqual(classifier.classify("Apple Music 3 Monate für 1,99€", ""), ["Musik-Abo"])

        classifier.httpx.post = lambda *args, **kwargs: _RateLimitedResponse()
        self.assertEqual(classifier.classify("Direktflüge: Griechenland ab Berlin", ""), ["Flug"])

    def test_unauthorized_response_disables_remote_calls_for_process(self):
        calls = 0

        def post(*args, **kwargs):
            nonlocal calls
            calls += 1
            return _UnauthorizedResponse()

        classifier.httpx.post = post
        self.assertEqual(classifier.classify("Apple Music 3 Monate für 1,99€", ""), ["Musik-Abo"])
        self.assertEqual(classifier.classify("Direktflüge: Griechenland ab Berlin", ""), ["Flug"])
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
