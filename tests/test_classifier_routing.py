import unittest

import app.classifier as classifier


class _Response:
    def __init__(self, status_code=200, content="Werkzeug"):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class _EmptyChoicesResponse(_Response):
    def json(self):
        return {"choices": []}


class ClassifierRoutingTest(unittest.TestCase):
    def setUp(self):
        self._values = {
            name: getattr(classifier, name)
            for name in ("PROVIDER", "API_URL", "API_KEY", "MODEL",
                         "MIN_DELAY_SECONDS", "_remote_disabled_reason",
                         "_last_call_at", "get_known_groups")
        }
        classifier.PROVIDER = "scaleway"
        classifier.API_URL = "https://api.scaleway.ai/v1/chat/completions"
        classifier.API_KEY = "test-only"
        classifier.MODEL = "mistral-small-3.2-24b-instruct-2506"
        classifier.MIN_DELAY_SECONDS = 0
        classifier._remote_disabled_reason = None
        classifier._last_call_at = 0
        classifier.get_known_groups = lambda: []
        classifier._decision_counts.clear()
        self._post = classifier.httpx.post
        self._sleep = classifier.time.sleep
        classifier.time.sleep = lambda seconds: None

    def tearDown(self):
        classifier.httpx.post = self._post
        classifier.time.sleep = self._sleep
        for name, value in self._values.items():
            setattr(classifier, name, value)
        classifier._decision_counts.clear()

    def test_clear_rule_does_not_call_llm(self):
        def fail_if_called(*args, **kwargs):
            raise AssertionError("eine eindeutige Regel darf keinen LLM-Aufruf auslösen")

        classifier.httpx.post = fail_if_called
        self.assertEqual(
            classifier.classify("Philips 55OLED810/12 Ambilight Smart TV", ""),
            ["Fernseher"],
        )
        self.assertEqual(
            classifier.get_decision_metrics(),
            {"rule_decision": 1, "llm_decision": 0, "fallback_decision": 0},
        )

    def test_boundary_calls_scaleway_once_with_qualified_model(self):
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response(content="Werkzeug")

        classifier.httpx.post = post
        self.assertEqual(
            classifier.classify("Unbekannter Haushaltsartikel stark reduziert", ""),
            ["Werkzeug"],
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "https://api.scaleway.ai/v1/chat/completions")
        self.assertEqual(calls[0][1]["json"]["model"], "mistral-small-3.2-24b-instruct-2506")
        self.assertEqual(
            classifier.get_decision_metrics(),
            {"rule_decision": 0, "llm_decision": 1, "fallback_decision": 0},
        )

    def test_invalid_output_is_fail_closed_and_never_uses_openrouter(self):
        calls = []

        def post(url, **kwargs):
            calls.append(url)
            return _EmptyChoicesResponse()

        classifier.httpx.post = post
        self.assertEqual(
            classifier.classify("Unbekannter Haushaltsartikel", ""),
            ["Sonstige Deals"],
        )
        self.assertEqual(calls, ["https://api.scaleway.ai/v1/chat/completions"] * 4)
        self.assertEqual(classifier.get_decision_metrics()["llm_decision"], 0)
        self.assertEqual(classifier.get_decision_metrics()["fallback_decision"], 1)

    def test_timeout_429_5xx_and_empty_output_use_local_fallback(self):
        cases = [
            lambda: (_ for _ in ()).throw(TimeoutError("timeout")),
            lambda: _Response(status_code=429),
            lambda: _Response(status_code=503),
            lambda: _Response(content=""),
        ]
        for make_response in cases:
            with self.subTest(response=make_response):
                classifier._remote_disabled_reason = None
                classifier._decision_counts.clear()
                classifier.httpx.post = lambda *args, **kwargs: make_response()
                self.assertEqual(
                    classifier.classify("Unbekannter Haushaltsartikel", ""),
                    ["Sonstige Deals"],
                )
                self.assertEqual(classifier.get_decision_metrics()["llm_decision"], 0)
                self.assertEqual(classifier.get_decision_metrics()["fallback_decision"], 1)

    def test_missing_remote_key_uses_fallback_without_provider_switch(self):
        classifier.API_KEY = ""
        classifier.httpx.post = lambda *args, **kwargs: self.fail("kein Remote-Aufruf erwartet")
        self.assertEqual(
            classifier.classify("Unbekannter Haushaltsartikel", ""),
            ["Sonstige Deals"],
        )
        self.assertEqual(classifier.get_decision_metrics()["fallback_decision"], 1)


if __name__ == "__main__":
    unittest.main()
