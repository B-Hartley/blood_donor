from datetime import datetime
from typing import Dict, List, Optional


def get_next_appointment(appointments: List[Dict]) -> Optional[Dict]:
    """Return the next appointment from the list sorted by date."""
    if not appointments:
        return None

    try:
        sorted_appointments = sorted(
            appointments,
            key=lambda x: datetime.strptime(
                x["session"]["sessionDate"].split("T")[0], "%Y-%m-%d"
            ),
        )
        return sorted_appointments[0]
    except (KeyError, ValueError, IndexError):
        return None
