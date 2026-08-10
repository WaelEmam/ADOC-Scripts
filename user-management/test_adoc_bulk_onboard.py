import pathlib
import tempfile
import unittest

from adoc_bulk_onboard import (
    ADOCError,
    chunked,
    extract_list,
    fetch_group_ids,
    group_by_groupset,
    invite_batch,
    limit_rows_by_user,
    read_csv_rows,
    read_env_file,
    resolve_group_ids,
    summarize_by_email,
)


class FakeClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def request(self, method, path, *, body=None):
        self.calls.append((method, path, body))
        return self.responses.get(path, {"status": True})


class BulkOnboardTests(unittest.TestCase):
    def test_read_csv_rows_parses_variable_number_of_groups_per_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "users.csv"
            path.write_text(
                "alice@example.com,Admins,Viewers\n"
                "bob@example.com,Viewers\n",
                encoding="utf-8",
            )
            rows = read_csv_rows(path)
            self.assertEqual(
                rows,
                [
                    ("alice@example.com", "Admins"),
                    ("alice@example.com", "Viewers"),
                    ("bob@example.com", "Viewers"),
                ],
            )

    def test_read_csv_rows_skips_header_row_without_at_sign(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "users.csv"
            path.write_text("email,groups\nalice@example.com,Admins\n", encoding="utf-8")
            self.assertEqual(read_csv_rows(path), [("alice@example.com", "Admins")])

    def test_read_csv_rows_drops_exact_duplicate_pairs_on_same_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "users.csv"
            path.write_text("alice@example.com,Admins,Admins\n", encoding="utf-8")
            self.assertEqual(read_csv_rows(path), [("alice@example.com", "Admins")])

    def test_read_csv_rows_rejects_row_with_no_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "users.csv"
            path.write_text("alice@example.com\n", encoding="utf-8")
            with self.assertRaises(ADOCError):
                read_csv_rows(path)

    def test_read_csv_rows_rejects_invalid_email_past_the_first_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "users.csv"
            path.write_text(
                "alice@example.com,Admins\nnot-an-email,Viewers\n", encoding="utf-8"
            )
            with self.assertRaises(ADOCError):
                read_csv_rows(path)

    def test_summarize_by_email_groups_multiple_rows(self):
        rows = [
            ("alice@example.com", "Admins"),
            ("alice@example.com", "Viewers"),
            ("bob@example.com", "Viewers"),
        ]
        self.assertEqual(
            summarize_by_email(rows),
            {"alice@example.com": ["Admins", "Viewers"], "bob@example.com": ["Viewers"]},
        )

    def test_group_by_groupset_keeps_same_group_users_together(self):
        rows = [
            ("alice@example.com", "Admins"),
            ("alice@example.com", "Viewers"),
            ("bob@example.com", "Viewers"),
            ("bob@example.com", "Admins"),
            ("carol@example.com", "Viewers"),
        ]
        self.assertEqual(
            group_by_groupset(rows),
            {
                ("Admins", "Viewers"): ["alice@example.com", "bob@example.com"],
                ("Viewers",): ["carol@example.com"],
            },
        )

    def test_limit_rows_by_user_keeps_all_groups_for_selected_users(self):
        rows = [
            ("alice@example.com", "Admins"),
            ("alice@example.com", "Viewers"),
            ("bob@example.com", "Viewers"),
        ]
        self.assertEqual(
            limit_rows_by_user(rows, 1),
            [("alice@example.com", "Admins"), ("alice@example.com", "Viewers")],
        )

    def test_limit_rows_by_user_rejects_non_positive_limit(self):
        with self.assertRaises(ADOCError):
            limit_rows_by_user([("alice@example.com", "Admins")], 0)

    def test_chunked_splits_into_requested_batch_size(self):
        items = [f"user{i}@example.com" for i in range(5)]
        batches = list(chunked(items, 2))
        self.assertEqual(
            batches,
            [
                ["user0@example.com", "user1@example.com"],
                ["user2@example.com", "user3@example.com"],
                ["user4@example.com"],
            ],
        )

    def test_chunked_rejects_non_positive_batch_size(self):
        with self.assertRaises(ADOCError):
            list(chunked(["a@example.com"], 0))

    def test_extract_list_finds_known_candidate_key(self):
        payload = {"groups": [{"id": "1", "name": "Admins"}], "message": ""}
        self.assertEqual(extract_list(payload, ("groups", "result")), [{"id": "1", "name": "Admins"}])

    def test_extract_list_falls_back_to_sole_list_valued_key(self):
        payload = {"data": [{"id": "1"}], "message": ""}
        self.assertEqual(extract_list(payload, ("groups", "result")), [{"id": "1"}])

    def test_extract_list_rejects_response_with_no_list(self):
        with self.assertRaises(ADOCError):
            extract_list({"message": "ok"}, ("groups",))

    def test_fetch_group_ids_maps_group_name_to_id(self):
        client = FakeClient(
            responses={
                "/admin/api/groups": {
                    "groups": [
                        {"id": "9fb4b956-fea2-47ea-b00c-072886426b36", "name": "leo-admins"},
                        {"id": "b325f591-7642-4429-9a22-794cef82f14a", "name": "leo-restricted"},
                    ]
                }
            }
        )
        self.assertEqual(
            fetch_group_ids(client),
            {
                "leo-admins": "9fb4b956-fea2-47ea-b00c-072886426b36",
                "leo-restricted": "b325f591-7642-4429-9a22-794cef82f14a",
            },
        )

    def test_resolve_group_ids_maps_names_to_ids(self):
        group_ids = {"Admins": "id-1", "Viewers": "id-2"}
        self.assertEqual(resolve_group_ids(("Admins", "Viewers"), group_ids), ["id-1", "id-2"])

    def test_resolve_group_ids_rejects_unknown_group_name(self):
        with self.assertRaises(ADOCError):
            resolve_group_ids(("Admins", "Nonexistent"), {"Admins": "id-1"})

    def test_invite_batch_sends_userdetails_wrapper_with_top_level_groups(self):
        client = FakeClient()
        invite_batch(client, ["alice@example.com", "bob@example.com"], ("Admins", "Viewers"), False)
        self.assertEqual(
            client.calls,
            [
                (
                    "POST",
                    "/admin/api/users/invite-users",
                    {
                        "userDetails": [{"email": "alice@example.com"}, {"email": "bob@example.com"}],
                        "groups": ["Admins", "Viewers"],
                        "sendEmail": False,
                    },
                )
            ],
        )

    def test_env_file_supports_quotes_comments_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / ".env"
            path.write_text(
                "# credentials\n"
                "export ADOC_URL='https://example.acceldata.app'\n"
                "ADOC_ACCESS_KEY=key-value # local key\n",
                encoding="utf-8",
            )
            self.assertEqual(
                read_env_file(path),
                {
                    "ADOC_URL": "https://example.acceldata.app",
                    "ADOC_ACCESS_KEY": "key-value",
                },
            )


if __name__ == "__main__":
    unittest.main()
