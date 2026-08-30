import unittest
from datetime import datetime, timezone

from app.backend.main import _utc_bounds_for_local_day


class TimeSummaryTimezoneTests(unittest.TestCase):
    def test_local_day_uses_the_users_iana_timezone(self):
        start, end = _utc_bounds_for_local_day(
            "America/Toronto",
            datetime(2026, 8, 25, 2, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(start, datetime(2026, 8, 24, 4, 0))
        self.assertEqual(end, datetime(2026, 8, 25, 4, 0))

    def test_local_day_bounds_follow_daylight_saving_transitions(self):
        start, end = _utc_bounds_for_local_day(
            "America/Toronto",
            datetime(2026, 3, 8, 16, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(start, datetime(2026, 3, 8, 5, 0))
        self.assertEqual(end, datetime(2026, 3, 9, 4, 0))

    def test_unknown_timezones_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown time zone"):
            _utc_bounds_for_local_day("Not/A_Timezone")


if __name__ == "__main__":
    unittest.main()
