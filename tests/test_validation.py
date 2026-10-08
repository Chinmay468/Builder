#!/usr/bin/env python3
"""
tests/test_validation.py — Unit tests for pure validation and helper functions
in resume_tailor.py using Python's standard library unittest.
"""

import argparse
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from resume_tailor import (
    braces_balanced,
    extract_latex,
    looks_like_latex,
    load_job_description,
    print_diff,
    validate_output,
)


class TestBracesBalanced(unittest.TestCase):
    def test_simple_balanced(self):
        self.assertTrue(braces_balanced(r"\textbf{Simple text}"))

    def test_nested_balanced(self):
        self.assertTrue(braces_balanced(r"\section{\textbf{\textit{Nested Title}}}"))

    def test_escaped_braces(self):
        # Escaped braces \{ and \} shouldn't count towards depth
        self.assertTrue(braces_balanced(r"Set \{a, b\} is valid: \textbf{cool}"))

    def test_unbalanced_open(self):
        self.assertFalse(braces_balanced(r"\textbf{missing closing brace"))

    def test_unbalanced_close(self):
        self.assertFalse(braces_balanced(r"\textbf{extra closing brace}}"))

    def test_negative_depth_reversal(self):
        # Even though count of { equals }, closing appears before opening
        self.assertFalse(braces_balanced(r"close first } then open {"))

    def test_empty_string(self):
        self.assertTrue(braces_balanced(""))


class TestLooksLikeLatex(unittest.TestCase):
    def test_has_documentclass(self):
        self.assertTrue(looks_like_latex(r"\documentclass[10pt]{article}"))

    def test_has_begin_document(self):
        self.assertTrue(looks_like_latex(r"\begin{document} Content \end{document}"))

    def test_has_section(self):
        self.assertTrue(looks_like_latex(r"\section{Experience}"))

    def test_plain_text_fails(self):
        self.assertFalse(looks_like_latex("This is just a plain text resume without markup."))

    def test_markdown_fails(self):
        self.assertFalse(looks_like_latex("# Resume\n## Experience\n- Built web apps"))


class TestExtractLatex(unittest.TestCase):
    def test_extract_latex_fence(self):
        raw = "```latex\n\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n```"
        expected = "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}"
        self.assertEqual(extract_latex(raw), expected)

    def test_extract_tex_fence(self):
        raw = "```tex\n\\documentclass{article}\n```"
        expected = "\\documentclass{article}"
        self.assertEqual(extract_latex(raw), expected)

    def test_extract_generic_fence(self):
        raw = "Here is your resume:\n```\n\\documentclass{article}\n```\nHope you like it!"
        expected = "\\documentclass{article}"
        self.assertEqual(extract_latex(raw), expected)

    def test_extract_no_fence(self):
        raw = "\\documentclass{article}\n\\begin{document}\nNo fences\n\\end{document}"
        self.assertEqual(extract_latex(raw), raw)


class TestLoadJobDescription(unittest.TestCase):
    def test_load_from_raw_text(self):
        args = argparse.Namespace(job_url=None, job="Software Engineer needed with Python and SQL experience.")
        result = load_job_description(args)
        self.assertEqual(result, "Software Engineer needed with Python and SQL experience.")

    def test_load_from_file(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
            tmp.write("Target Job: Senior Backend Engineer at Stripe.")
            tmp_path = tmp.name

        try:
            args = argparse.Namespace(job_url=None, job=tmp_path)
            result = load_job_description(args)
            self.assertEqual(result, "Target Job: Senior Backend Engineer at Stripe.")
        finally:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)

    def test_missing_both_raises_value_error(self):
        args = argparse.Namespace(job_url=None, job=None)
        with self.assertRaises(ValueError):
            load_job_description(args)

    @patch("resume_tailor.fetch_job_from_url")
    def test_load_from_url(self, mock_fetch):
        mock_fetch.return_value = "Fetched Job Posting Description"
        args = argparse.Namespace(job_url="https://jobs.example.com/123", job=None)
        result = load_job_description(args)
        self.assertEqual(result, "Fetched Job Posting Description")
        mock_fetch.assert_called_once_with("https://jobs.example.com/123")


class TestPrintDiff(unittest.TestCase):
    def test_diff_identical(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            print_diff("same line\n", "same line\n")
        output = buf.getvalue()
        self.assertIn("No textual changes detected", output)

    def test_diff_with_changes(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            print_diff("old line\n", "new line\n")
        output = buf.getvalue()
        self.assertIn("UNIFIED DIFF", output)
        self.assertIn("-old line", output)
        self.assertIn("+new line", output)


class TestValidateOutput(unittest.TestCase):
    def setUp(self):
        self.master_sample = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{+91 9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\begin{tabular}{ @{} >{\\bfseries}l @{\\hspace{2ex}} l }\n"
            "Languages :& Java, SQL \\\\\n"
            "\\end{tabular}\n"
            "\\begin{itemize}\n"
            "  \\item Solved 400+ problems on LeetCode.\n"
            "  \\item Review paper published.\n"
            "  \\item Java Development Certification.\n"
            "  \\item Full Stack Intern May 2026 -- June 2026.\n"
            "\\end{itemize}\n"
        )

    def test_valid_output_passes(self):
        self.assertTrue(validate_output(self.master_sample, self.master_sample))

    def test_name_changed_fails(self):
        tampered = self.master_sample.replace("Chinmay Maheshwari", "John Doe")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_phone_changed_fails(self):
        tampered = self.master_sample.replace("9460449962", "1234567890")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_email_changed_fails(self):
        tampered = self.master_sample.replace("chinmaymaheshwari.it27@gmail.com", "other@gmail.com")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_research_paper_instead_of_review_paper_fails(self):
        tampered = self.master_sample.replace("Review paper", "Research paper")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_professional_java_fails(self):
        tampered = self.master_sample.replace("Java Development Certification", "Professional Java Development Certification")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_wrong_leetcode_count_fails(self):
        tampered = self.master_sample.replace("400+", "500+")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_ongoing_internship_fails(self):
        tampered = self.master_sample.replace("May 2026 -- June 2026", "May 2026 -- Present")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_broken_itemize_fails(self):
        tampered = self.master_sample.replace("\\begin{itemize}", "-- bullet points")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_broken_skills_tabular_fails(self):
        tampered = self.master_sample.replace(">{\\bfseries}l", "ll")
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_unsupported_tdd_claim_in_summary_fails(self):
        tampered = (
            "\\begin{rSection}{SUMMARY}\n"
            "Proficient in TDD and microservices architecture.\n"
            "\\end{rSection}\n"
            + self.master_sample
        )
        self.assertFalse(validate_output(tampered, self.master_sample))

    def test_supported_testing_claim_in_summary_passes(self):
        tampered = (
            "\\begin{rSection}{SUMMARY}\n"
            "Strong focus on test coverage, integration testing, and reliability.\n"
            "\\end{rSection}\n"
            + self.master_sample
        )
        self.assertTrue(validate_output(tampered, self.master_sample))


if __name__ == "__main__":
    unittest.main()
