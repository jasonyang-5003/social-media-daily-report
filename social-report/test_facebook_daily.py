import unittest
from datetime import date
from facebook_backfill import missing_dates, merge_missing

from facebook_daily import parse_number, previous_month_totals, find_existing_row


def row(date, views="100", interactions="10", region="LATAM"):
    return [date, "Facebook", region] + [""] * 10 + [views, interactions]


class FacebookMetricsTests(unittest.TestCase):
    def test_backfill_targets_missing_fields_not_snapshot_fields(self):
        complete = ["2026-10-07", "Facebook", "LATAM", "8000", "", "", "0"] + [""] * 8 + ["0", ""]
        partial = complete.copy()
        partial[0], partial[15] = "2026-10-08", ""
        self.assertEqual(missing_dates([[], complete, partial], date(2026,10,7), date(2026,10,9)),
                         ["2026-10-08", "2026-10-09"])

    def test_merge_only_missing_recoverable_fields_and_preserves_zero(self):
        old = ["2026-10-08", "Facebook", "LATAM", "8000", "", "", "0"] + [""] * 10
        old[8], old[13], old[12] = "123", "999", "success"
        source = old.copy()
        source[3], source[6], source[15], source[8] = 9000, 9, 0, 555
        result = merge_missing(old, source)
        self.assertEqual(result[3], "8000")
        self.assertEqual(result[6], "0")
        self.assertEqual(result[15], 0)
        self.assertEqual(result[8], "123")
        self.assertEqual(result[13], "999")
        self.assertEqual(result[12], "success")
        self.assertEqual(merge_missing(result, source), result)

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
