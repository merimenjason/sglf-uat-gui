import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


class DuplicateClaimUITests(unittest.TestCase):
    def start_app(self):
        app = AppTest.from_file(str(APP)).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def run_with_output(self, app, output, returncode=0):
        process = MagicMock()
        read_fd, write_fd = os.pipe()
        process.stdout = os.fdopen(read_fd, "r")
        os.write(write_fd, output.encode())
        os.close(write_fd)
        process.returncode = returncode
        process.poll.return_value = returncode
        try:
            with patch.object(subprocess, "Popen", return_value=process) as popen:
                app.button[0].click().run()
            self.assertTrue(process.stdout.closed)
        finally:
            process.stdout.close()
        self.assertEqual(len(app.exception), 0)
        return app.session_state["last_result"], popen.call_args.args[0]

    def test_duplicate_control_changes_button_and_keeps_confirmation_required(self):
        app = self.start_app()
        self.assertFalse(app.checkbox[0].value)
        self.assertEqual(app.number_input(key="submit_count").value, 1)
        self.assertEqual(app.button[0].label, "Submit dummy UAT claim")
        app.number_input(key="submit_count").set_value(5).run()
        self.assertEqual(app.button[0].label, "Submit same UAT claim 5 times")
        self.assertTrue(app.button[0].disabled)
        app.checkbox[0].check().run()
        self.assertFalse(app.button[0].disabled)

    def test_five_completed_submissions_are_reported_as_success(self):
        app = self.start_app()
        app.number_input(key="submit_count").set_value(5).run()
        app.checkbox[0].check().run()
        output = "".join(f"Submission {n} of 5 completed.\n" for n in range(1, 6))
        result, command = self.run_with_output(app, output)
        self.assertEqual(command[command.index("--submit-count") + 1], "5")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["submissions_requested"], 5)
        self.assertEqual(result["submissions_completed"], 5)
        self.assertIn("5 times", result["message"])
        self.assertIn("5 of 5", result["message"])

    def test_two_completed_submissions_are_reported_as_success(self):
        app = self.start_app()
        app.number_input(key="submit_count").set_value(2).run()
        app.checkbox[0].check().run()
        result, command = self.run_with_output(
            app, "Using policy number: 001MEDICAL250\nSubmission 1 of 2 completed.\nSubmission 2 of 2 completed.\n",
        )
        self.assertEqual(command[command.index("--submit-count") + 1], "2")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["submissions_completed"], 2)
        self.assertEqual(result["policy"], "001MEDICAL250")
        self.assertIn("2 of 2", result["message"])

    def test_second_attempt_failure_reports_partial_completion(self):
        app = self.start_app()
        app.number_input(key="submit_count").set_value(2).run()
        app.checkbox[0].check().run()
        result, command = self.run_with_output(app, "Submission 1 of 2 completed.\nDuplicate rejected\n", 1)
        self.assertEqual(command[command.index("--submit-count") + 1], "2")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["submissions_completed"], 1)
        self.assertIn("1 of 2", result["message"])

    def test_zero_exit_without_second_confirmation_is_not_double_success(self):
        app = self.start_app()
        app.number_input(key="submit_count").set_value(2).run()
        app.checkbox[0].check().run()
        result, _ = self.run_with_output(app, "Submission 1 of 2 completed.\n")
        self.assertEqual(result["status"], "failed")
        self.assertIn("1 of 2", result["message"])

    def test_single_submission_remains_the_default(self):
        app = self.start_app()
        app.checkbox[0].check().run()
        result, command = self.run_with_output(app, "Submission 1 of 1 completed.\n")
        self.assertNotIn("--submit-count", command)
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["submissions_requested"], 1)

    def test_switching_to_review_removes_duplicate_submission(self):
        app = self.start_app()
        app.number_input(key="submit_count").set_value(3).run()
        app.radio[1].set_value("Review before submission").run()
        self.assertEqual(len(app.checkbox), 0)
        self.assertNotIn("submit_count", [widget.key for widget in app.number_input])
        self.assertEqual(app.button[0].label, "Prepare review")
        result, command = self.run_with_output(app, "Stopped before Confirm.\n")
        self.assertIn("--no-submit", command)
        self.assertNotIn("--submit-count", command)
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(result["submissions_completed"], 0)


if __name__ == "__main__":
    unittest.main()
