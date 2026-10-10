import unittest

from facebook_daily import parse_number, previous_month_totals, find_existing_row


def row(date, views="100", interactions="10", region="LATAM"):
    return [date, "Facebook", region] + [""] * 10 + [views, interactions]


class FacebookMetricsTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        self.assertIsNone(parse_number("-"))
        self.assertIsNone(parse_number(""))
        self.assertEqual(parse_number("0"), 0)
        self.assertEqual(parse_number("8,086"), 8086)

    def test_snapshot_must_be_previous_day(self):
        self.assertIsNone(previous_month_totals([[], row("2026-10-07")], "2026-10-09"))
        self.assertEqual(previous_month_totals([[], row("2026-10-08")], "2026-10-09"),
                         ("2026-10-08", 100, 10))

    def test_month_reset_and_missing_snapshot(self):
        self.assertIsNone(previous_month_totals([[], row("2026-09-30")], "2026-10-01"))
        self.assertIsNone(previous_month_totals([[], row("2026-10-08", "")], "2026-10-09"))

    def test_upsert_includes_region(self):
        self.assertIsNone(find_existing_row([[], row("2026-10-09", region="US")], "2026-10-09"))
        self.assertEqual(find_existing_row([[], row("2026-10-09")], "2026-10-09"), 2)


if __name__ == "__main__":
    unittest.main()
