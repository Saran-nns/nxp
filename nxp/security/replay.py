"""
NXP Sliding-Window Replay Defense.

Complements per-frame SDMT authentication: a valid SDMT token only proves the
frame was produced under the correct session key, not that it hasn't been
captured off the wire and resent. ReplayWindow tracks recently-accepted
sequence numbers per session and rejects duplicates or frames that fall
outside the trailing window.
"""

from __future__ import annotations


class ReplayWindow:
    """
    Sliding bitmask window over per-session BFP sequence numbers.

    A frame with sequence ``seq`` is accepted iff:
      - ``seq > seq_max - window``  (not older than the trailing window edge)
      - ``seq`` has not already been recorded as seen within the window

    Implemented as a single Python integer bitmask (bit *i* set = the
    sequence number ``seq_max - i`` has been seen), which slides forward as
    new, higher sequence numbers arrive.
    """

    __slots__ = ("window", "seq_max", "_bitmap")

    def __init__(self, window: int = 64):
        self.window = window
        self.seq_max = -1
        self._bitmap = 0

    def accept(self, seq: int) -> bool:
        """Return True and record ``seq`` if it is a fresh, in-window sequence number."""
        if seq <= self.seq_max - self.window:
            return False  # too old — outside the trailing window

        if seq <= self.seq_max:
            offset = self.seq_max - seq
            if (self._bitmap >> offset) & 1:
                return False  # replay — this exact sequence was already accepted
            self._bitmap |= (1 << offset)
            return True

        # seq > seq_max: slide the window forward and mark the new head bit
        shift = seq - self.seq_max
        mask = (1 << self.window) - 1
        self._bitmap = (self._bitmap << shift) & mask
        self._bitmap |= 1
        self.seq_max = seq
        return True
