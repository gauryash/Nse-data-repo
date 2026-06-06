"""Unit tests for shared utilities."""

from nse_relative.shared.utils import make_date_chunks


class TestMakeDateChunks:
    def test_single_chunk(self):
        chunks = make_date_chunks("01-01-2026", "15-01-2026", chunk_days=30)
        assert len(chunks) == 1
        assert chunks[0] == ("01-01-2026", "15-01-2026")

    def test_multiple_chunks(self):
        chunks = make_date_chunks("01-01-2026", "01-03-2026", chunk_days=30)
        assert len(chunks) >= 2
        assert chunks[0][0] == "01-01-2026"

    def test_chunk_boundary(self):
        """Chunks should not overlap and should cover the full range."""
        chunks = make_date_chunks("01-01-2026", "31-03-2026", chunk_days=30)
        # Verify no gaps
        for i in range(len(chunks) - 1):
            from datetime import datetime
            end_current = datetime.strptime(chunks[i][1], "%d-%m-%Y")
            start_next = datetime.strptime(chunks[i + 1][0], "%d-%m-%Y")
            assert (start_next - end_current).days == 1, f"Gap between chunks {i} and {i+1}"
