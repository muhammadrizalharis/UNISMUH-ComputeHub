"""Riwayat pertumbuhan disk: baca tren CSV + rekaman lonjakan dari disk_growth_watch.sh."""

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import disk_growth


class DiskGrowthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "lonjakan").mkdir()
        self.patch = mock.patch.object(disk_growth, "log_dir", return_value=self.base)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def _write_trend(self, rows: list[tuple[dt.datetime, float, str]]) -> None:
        by_month: dict[str, list[str]] = {}
        for t, free, rate in rows:
            by_month.setdefault(t.strftime("%Y-%m"), []).append(
                f"{t:%Y-%m-%d %H:%M:%S},{free},80,{rate}"
            )
        for m, lines in by_month.items():
            (self.base / f"tren-{m}.csv").write_text(
                "waktu,sisa_gb,terpakai_pct,turun_gb_per_jam\n" + "\n".join(lines) + "\n"
            )

    def test_reads_trend_within_range_and_keeps_empty_rate(self) -> None:
        now = dt.datetime.now().replace(microsecond=0)
        self._write_trend([
            (now - dt.timedelta(days=10), 400.0, "1.0"),
            (now - dt.timedelta(hours=2), 350.0, ""),
            (now - dt.timedelta(hours=1), 220.0, "130.0"),
        ])
        out = disk_growth.growth(days=7)
        self.assertEqual([p["free_gb"] for p in out["points"]], [350.0, 220.0])
        self.assertIsNone(out["points"][0]["drop_gb_per_h"])
        self.assertEqual(out["max_drop_gb_per_h"], 130.0)
        self.assertEqual(out["latest"]["free_gb"], 220.0)

    def test_downsample_keeps_lowest_point(self) -> None:
        now = dt.datetime.now().replace(microsecond=0)
        rows = [(now - dt.timedelta(minutes=10 * i), 300.0, "") for i in range(1, 1000)]
        rows[500] = (rows[500][0], 100.0, "")
        self._write_trend(rows)
        out = disk_growth.growth(days=30)
        self.assertLessEqual(len(out["points"]), disk_growth.MAX_POINTS)
        self.assertIn(100.0, [p["free_gb"] for p in out["points"]])

    def test_lists_spikes_and_detail(self) -> None:
        name = dt.datetime.now().strftime("%Y%m%d-%H%M")
        (self.base / "lonjakan" / f"{name}.txt").write_text(
            "LONJAKAN DISK hpc-ai\n"
            "Sisa disk turun 130.0 GB dalam ~1 jam (laju 128.5 GB/jam). Sisa sekarang 196 GB.\n\n"
            "== Proses penulis terbesar (sampel 10 detik, kB_wr/s) ==\n"
            "root  pid=1  tulis=  70.0 MB/s  dockerd\n"
        )
        (self.base / "lonjakan" / "bukan-lonjakan.txt").write_text("x")
        spikes = disk_growth.growth(days=1)["spikes"]
        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0]["drop_gb"], 130.0)
        self.assertEqual(spikes[0]["rate_gb_per_h"], 128.5)
        self.assertIn("dockerd", spikes[0]["top_writer"])
        self.assertIn("LONJAKAN", disk_growth.spike_detail(name))

    def test_spike_detail_rejects_path_traversal(self) -> None:
        self.assertIsNone(disk_growth.spike_detail("../../etc/passwd"))
        self.assertIsNone(disk_growth.spike_detail("20260101-0000"))

    def test_missing_dir_is_empty(self) -> None:
        self.patch.stop()
        with mock.patch.object(disk_growth, "log_dir", return_value=self.base / "tidak-ada"):
            out = disk_growth.growth(days=7)
        self.patch.start()
        self.assertFalse(out["available"])
        self.assertEqual(out["points"], [])
        self.assertEqual(out["spikes"], [])


if __name__ == "__main__":
    unittest.main()
