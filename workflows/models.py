"""Shared data types passed between the ChronoLabs workflow and its activities."""

from dataclasses import dataclass


@dataclass
class TripRequest:
    destination: str
    mission: str = ""
    # Set from the UI so a presenter can reliably demo the review flow instead
    # of waiting for the random paradox scan to flag a trip.
    force_review: bool = False


@dataclass
class ScanResult:
    flagged: bool
    reason: str = ""


@dataclass
class GrantCheck:
    """Outcome of the delegation-grant check (`activities.verify_grant`).

    `reason` is a REJECT_* code for logging only — never a response body. The
    verified identity comes back with it so the startup interceptor can tag the
    execution without decoding the grant itself in the sandbox.
    """

    valid: bool
    reason: str = ""
    traveler_id: str = ""
    traveler_name: str = ""
