import contextlib
import copy
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import singlife_travel_claim as automation


class DuplicateClaimTests(unittest.TestCase):
    def browser(self):
        browser = MagicMock()
        contexts = []

        def new_context():
            context = MagicMock()
            context.__enter__.return_value = context
            contexts.append(context)
            return context

        browser.new_context.side_effect = new_context
        return browser, contexts

    def test_duplicate_payload_and_documents_match_for_every_scenario(self):
        variants = [
            ("medical", {"claim_amount": "199.99"}),
            ("baggage", {"item_amount": "88.50"}),
            ("flight_delay", {"flight": "AV222"}),
            ("flight_delay", {"flight": "SQ957"}),
        ]
        helpers = [
            "goto_and_start_claim", "fill_basic_details", "fill_insured_and_claimant",
            "fill_claim_details_common", "fill_medical_related", "fill_travel_inconvenience",
            "fill_property_damage", "go_next_from_claim_details",
            "upload_supporting_documents", "complete_declaration_and_submit",
        ]
        for case, options in variants:
            with self.subTest(case=case, options=options), contextlib.ExitStack() as stack:
                directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
                calls = []

                def recorder(name):
                    def record(page, *args, **kwargs):
                        if name == "goto_and_start_claim":
                            calls.append([])
                        if name == "upload_supporting_documents":
                            args = ([(path.name, path.read_bytes()) for path in args[0]],)
                        calls[-1].append((name, copy.deepcopy(args), copy.deepcopy(kwargs)))
                    return record

                for name in helpers:
                    stack.enter_context(patch.object(automation, name, side_effect=recorder(name)))
                identity = stack.enter_context(patch.object(
                    automation, "_random_claim_identity", wraps=automation._random_claim_identity,
                ))
                browser, contexts = self.browser()
                output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                automation.run_claims(
                    browser, directory, case=case, submit_twice=True,
                    run_kwargs={"policy_suffix": "DUP-42", "auto_submit": True, **options},
                )
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0], calls[1])
                self.assertEqual(len(contexts), 2)
                self.assertIsNot(contexts[0].new_page.return_value, contexts[1].new_page.return_value)
                for context in contexts:
                    context.__exit__.assert_called_once()
                identity.assert_called_once()
                self.assertIn("Submission 1 of 2 completed.", output.getvalue())
                self.assertIn("Submission 2 of 2 completed.", output.getvalue())

    def test_separate_runs_generate_new_identities_and_default_to_one_submission(self):
        identities = [
            automation.ClaimIdentity("Tan", "Alex", "001", "S0000001A"),
            automation.ClaimIdentity("Lim", "Bella", "002", "S0000002A"),
        ]
        browser, contexts = self.browser()
        case = MagicMock()
        with patch.dict(automation.CASES, medical=case), patch.object(
            automation, "_random_claim_identity", side_effect=identities,
        ), contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                automation.run_claims(browser, Path("."), case="medical", run_kwargs={"auto_submit": True})
        self.assertEqual(case.call_count, 2)
        self.assertEqual(len(contexts), 2)
        self.assertEqual([call.kwargs["identity"] for call in case.call_args_list], identities)

    def test_failure_stops_without_retry_and_reports_only_completed_attempts(self):
        for failure_at in (1, 2):
            with self.subTest(failure_at=failure_at):
                browser, contexts = self.browser()
                effects = [None] * (failure_at - 1) + [RuntimeError("Portal refused the claim")]
                case = MagicMock(side_effect=effects)
                with patch.dict(automation.CASES, medical=case), contextlib.redirect_stdout(
                    io.StringIO()
                ) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
                    with self.assertRaisesRegex(RuntimeError, "Portal refused"):
                        automation.run_claims(
                            browser, Path("."), case="medical", submit_twice=True,
                            run_kwargs={"auto_submit": True},
                        )
                self.assertEqual(case.call_count, failure_at)
                self.assertEqual(len(contexts), failure_at)
                self.assertEqual(output.getvalue().count("completed."), failure_at - 1)
                self.assertIn("Failure screenshot saved to", errors.getvalue())
                contexts[-1].new_page.return_value.screenshot.assert_called_once()
                for context in contexts:
                    context.__exit__.assert_called_once()

    def test_review_prepares_once_without_reporting_a_submission(self):
        browser, contexts = self.browser()
        case = MagicMock()
        with patch.dict(automation.CASES, medical=case), contextlib.redirect_stdout(io.StringIO()) as output:
            automation.run_claims(
                browser, Path("."), case="medical", run_kwargs={"auto_submit": False},
            )
        self.assertEqual(len(contexts), 1)
        self.assertFalse(case.call_args.kwargs["auto_submit"])
        self.assertNotIn("completed.", output.getvalue())

    def test_duplicate_review_is_rejected_before_opening_a_browser_context(self):
        browser, _ = self.browser()
        with self.assertRaises(ValueError):
            automation.run_claims(
                browser, Path("."), case="medical", submit_twice=True,
                run_kwargs={"auto_submit": False},
            )
        browser.new_context.assert_not_called()

    def test_cli_rejects_submit_twice_with_no_submit(self):
        with patch("sys.argv", ["claim", "--case", "medical", "--submit-twice", "--no-submit"]), patch.object(
            automation, "sync_playwright",
        ) as playwright, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                automation.main()
        self.assertEqual(error.exception.code, 2)
        playwright.assert_not_called()

    def test_cli_forwards_duplicate_options_and_closes_browser_on_failure(self):
        arguments = ["claim", "--case", "flight_delay", "--flight", "SQ957", "--submit-twice"]
        with patch("sys.argv", arguments), patch.object(automation, "sync_playwright") as playwright, patch.object(
            automation, "run_claims", side_effect=RuntimeError("Submission failed"),
        ) as runner:
            with self.assertRaisesRegex(RuntimeError, "Submission failed"):
                automation.main()
        self.assertTrue(runner.call_args.kwargs["submit_twice"])
        self.assertEqual(runner.call_args.kwargs["run_kwargs"]["flight"], "SQ957")
        playwright.return_value.__enter__.return_value.chromium.launch.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
