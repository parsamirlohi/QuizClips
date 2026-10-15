import unittest
from unittest.mock import Mock, patch
import requests
import questions


def response(code, results=None, status=200):
    r = Mock(status_code=status)
    r.json.return_value = {"response_code": code, "results": results or []}
    return r


class TriviaDatabaseTests(unittest.TestCase):
    @patch.object(questions.time, "sleep")
    def test_smaller_batch_after_insufficient_questions(self, sleep):
        with patch.object(questions.requests, "get", side_effect=[
                response(1), response(1), response(0, [{"question": "real db question"}])]) as get:
            self.assertEqual(len(questions._fetch_category(27, 50)), 1)
        urls = [c.args[0] for c in get.call_args_list]
        self.assertIn("amount=50", urls[0])
        self.assertIn("amount=25", urls[1])
        self.assertIn("amount=12", urls[2])
        self.assertTrue(all("category=27" in url and "difficulty=easy" in url for url in urls))
        self.assertEqual(sleep.call_count, 2)

    @patch.object(questions.time, "sleep")
    def test_empty_category_terminates_at_one(self, sleep):
        with patch.object(questions.requests, "get", return_value=response(1)) as get:
            self.assertEqual(questions._fetch_category(27, 3), [])
        self.assertEqual(get.call_count, 2)

    @patch.object(questions.time, "sleep")
    def test_rate_limit_then_success_keeps_batch_size(self, sleep):
        with patch.object(questions.requests, "get", side_effect=[response(5), response(0, ["question"])]) as get:
            self.assertEqual(questions._fetch_category(22, 20), ["question"])
        self.assertEqual(get.call_args_list[0], get.call_args_list[1])

    @patch.object(questions.time, "sleep")
    def test_rate_limit_exhaustion_is_specific(self, sleep):
        with patch.object(questions.requests, "get", return_value=response(5)):
            with self.assertRaisesRegex(RuntimeError, "rate-limiting"):
                questions._fetch_category(22)
        self.assertEqual(sleep.call_count, 2)

    @patch.object(questions.time, "sleep")
    def test_connection_failure_is_specific(self, sleep):
        with patch.object(questions.requests, "get", side_effect=requests.ConnectionError()):
            with self.assertRaisesRegex(RuntimeError, "internet connection"):
                questions._fetch_category(22)

    def test_invalid_parameters_do_not_retry(self):
        with patch.object(questions.requests, "get", return_value=response(2)) as get:
            with self.assertRaisesRegex(RuntimeError, "parameters"):
                questions._fetch_category(22)
        get.assert_called_once()
