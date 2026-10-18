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
    compile_pdf,
    extract_latex,
    extract_master_facts,
    get_pdf_page_count,
    looks_like_latex,
    load_job_description,
    print_diff,
    tailor_resume,
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


class TestExtractMasterFacts(unittest.TestCase):
    def test_extract_facts_from_master_sample(self):
        sample = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{+91 9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\textbf{B.Tech in Information Technology} \\hfill {2023 -- 2027}\n"
            "\\\\ CGPA : 8.8\n"
            "\\item Full Stack Intern \\hfill {May 2026 -- June 2026}\n"
            "\\item Solved \\textbf{400+} DSA problems across LeetCode\n"
            "\\item Earned a Java Development Certification.\n"
            "\\item Published a review paper in \\textbf{Pratibodh}\n"
        )
        facts = extract_master_facts(sample)
        self.assertEqual(facts["name"], "Chinmay Maheshwari")
        self.assertEqual(facts["phone"], "9460449962")
        self.assertEqual(facts["email"], "chinmaymaheshwari.it27@gmail.com")
        self.assertEqual(facts["cgpa"], "8.8")
        self.assertEqual(facts["grad_years"], "2023 -- 2027")
        self.assertEqual(facts["internship_dates"], "May 2026 -- June 2026")
        self.assertEqual(facts["dsa_count"], "400+")
        self.assertEqual(facts["cert_name"], "Java Development Certification")
        self.assertEqual(facts["publication_type"], "review paper")

    def test_extract_facts_with_custom_values(self):
        sample = (
            "\\documentclass{resume}\n"
            "\\name{Jane Doe}\n"
            "\\address{+1 5551234567 \\\\ jane@example.com}\n"
            "\\textbf{B.Tech in IT} \\hfill {2022 -- 2026}\n"
            "\\\\ CGPA : 9.2\n"
            "\\item Software Engineering Intern \\hfill {June 2025 -- August 2025}\n"
            "\\item Solved 500+ problems on LeetCode\n"
            "\\item Earned an AWS Cloud Practitioner Certification.\n"
        )
        facts = extract_master_facts(sample)
        self.assertEqual(facts["name"], "Jane Doe")
        self.assertEqual(facts["phone"], "15551234567")
        self.assertEqual(facts["email"], "jane@example.com")
        self.assertEqual(facts["cgpa"], "9.2")
        self.assertEqual(facts["grad_years"], "2022 -- 2026")
        self.assertEqual(facts["internship_dates"], "June 2025 -- August 2025")
        self.assertEqual(facts["dsa_count"], "500+")
        self.assertEqual(facts["cert_name"], "AWS Cloud Practitioner Certification")


class TestDynamicFactValidation(unittest.TestCase):
    def test_dynamic_dsa_count_passes_when_matching_master_300(self):
        master_300 = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\item Solved 300+ problems on LeetCode\n"
            "\\item Review paper published.\n"
            "\\item Java Development Certification.\n"
            "\\begin{itemize} \\item test \\end{itemize}\n"
            ">{\\bfseries}l\n"
        )
        tailored_300 = master_300
        # When master has 300+, tailored with 300+ MUST pass!
        self.assertTrue(validate_output(tailored_300, master_300))

    def test_dynamic_dsa_count_fails_when_drifting_from_master_300_to_400(self):
        master_300 = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\item Solved 300+ problems on LeetCode\n"
            "\\item Review paper published.\n"
            "\\item Java Development Certification.\n"
            "\\begin{itemize} \\item test \\end{itemize}\n"
            ">{\\bfseries}l\n"
        )
        tailored_400 = master_300.replace("300+", "400+")
        self.assertFalse(validate_output(tailored_400, master_300))

    def test_dynamic_dsa_count_passes_when_matching_master_500(self):
        master_500 = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\item Solved 500+ problems on LeetCode\n"
            "\\item Review paper published.\n"
            "\\item Java Development Certification.\n"
            "\\begin{itemize} \\item test \\end{itemize}\n"
            ">{\\bfseries}l\n"
        )
        tailored_500 = master_500
        # When master has 500+, tailored with 500+ MUST pass!
        self.assertTrue(validate_output(tailored_500, master_500))


class TestValidationRetryGating(unittest.TestCase):
    @patch("resume_tailor.call_groq")
    @patch("resume_tailor.get_groq_api_keys", return_value=["dummy_key"])
    def test_tailor_resume_retries_and_succeeds(self, mock_keys, mock_groq):
        master_sample = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\item Solved 400+ problems on LeetCode\n"
            "\\item Review paper published.\n"
            "\\item Java Development Certification.\n"
            "\\begin{itemize} \\item test \\end{itemize}\n"
            ">{\\bfseries}l\n"
        )
        # First call has wrong LeetCode count (500+), second call fixes it to 400+
        bad_output = master_sample.replace("400+", "500+")
        good_output = master_sample
        mock_groq.side_effect = [bad_output, good_output]

        result = tailor_resume(master_sample, "Job Description", api_key="dummy_key")
        self.assertEqual(mock_groq.call_count, 2)
        self.assertIn("400+", result)

    @patch("resume_tailor.call_groq")
    @patch("resume_tailor.get_groq_api_keys", return_value=["dummy_key"])
    def test_tailor_resume_fails_loudly_when_retry_also_invalid(self, mock_keys, mock_groq):
        master_sample = (
            "\\documentclass{resume}\n"
            "\\name{Chinmay Maheshwari}\n"
            "\\address{9460449962 \\\\ chinmaymaheshwari.it27@gmail.com}\n"
            "\\item Solved 400+ problems on LeetCode\n"
            "\\item Review paper published.\n"
            "\\item Java Development Certification.\n"
            "\\begin{itemize} \\item test \\end{itemize}\n"
            ">{\\bfseries}l\n"
        )
        # Both calls return wrong count
        bad_output = master_sample.replace("400+", "500+")
        mock_groq.side_effect = [bad_output, bad_output]

        with self.assertRaises(ValueError) as ctx:
            tailor_resume(master_sample, "Job Description", api_key="dummy_key")
        self.assertIn("validation failed after retry", str(ctx.exception))
        self.assertEqual(mock_groq.call_count, 2)


class TestPdfCompilationAndPageCount(unittest.TestCase):
    def test_get_pdf_page_count_nonexistent_returns_0(self):
        self.assertEqual(get_pdf_page_count("non_existent_file.pdf"), 0)

    def test_get_pdf_page_count_for_master_resume(self):
        if os.path.isfile("master_resume.pdf"):
            count = get_pdf_page_count("master_resume.pdf")
            self.assertEqual(count, 1)

    @patch("resume_tailor.subprocess.run")
    @patch("os.path.isfile", return_value=True)
    @patch("resume_tailor.get_pdf_page_count", return_value=2)
    def test_compile_pdf_fails_on_page_overflow(self, mock_count, mock_isfile, mock_subproc):
        # Even when compiler returns 0 and file exists, page_count > 1 must fail compile_pdf
        res = compile_pdf("master_resume.tex")
        self.assertFalse(res)

    @patch("resume_tailor.subprocess.run")
    @patch("os.path.isfile", return_value=True)
    @patch("resume_tailor.get_pdf_page_count", return_value=1)
    def test_compile_pdf_succeeds_on_single_page(self, mock_count, mock_isfile, mock_subproc):
        res = compile_pdf("master_resume.tex")
        self.assertTrue(res)


if __name__ == "__main__":
    unittest.main()
