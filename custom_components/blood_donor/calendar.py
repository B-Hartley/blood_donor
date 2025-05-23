"""Calendar platform for Blood Donor integration."""
import logging
from datetime import datetime, timedelta, time

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import DOMAIN, BloodDonorDataUpdateCoordinator
from .utils import get_next_appointment

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Blood Donor calendar based on a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([BloodDonorCalendar(coordinator)], True)


class BloodDonorCalendar(CoordinatorEntity, CalendarEntity):
    """Blood Donor Calendar."""

    def __init__(self, coordinator):
        """Initialize the calendar."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_name = "Appointments"
        
        # Format registration date for device info if available
        registration_date_str = "Unknown"
        if coordinator.data and "awards" in coordinator.data:
            registration_date = coordinator.data.get("awards", {}).get("registrationDate")
            if registration_date:
                try:
                    date_obj = datetime.strptime(registration_date.split("T")[0], "%Y-%m-%d")
                    registration_date_str = date_obj.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    registration_date_str = "Unknown"
        
        # Get blood group for device info
        blood_group = "Unknown"
        if coordinator.data:
            blood_group = coordinator.data.get("bloodGroup", "Unknown")
        
        # Update device info format
        donation_type = coordinator.api._procedure_type or "Unknown"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.api._donor_id)},
            "name": "Blood Donor",
            "manufacturer": "Blood.co.uk",
            "model": f"{donation_type} Donor ({blood_group}) since {registration_date_str}",
            "serial_number": coordinator.api._donor_id or "Unknown",
        }
        
        self._attr_unique_id = f"{coordinator.api._donor_id}_calendar"

    @property
    def event(self):
        """Return the next upcoming event."""
        if not self.coordinator.data:
            return None
            
        appointments = self.coordinator.data.get("appointments", [])
        if not appointments:
            return None
            
        try:
            next_appointment = get_next_appointment(appointments)
            if not next_appointment:
                return None

            # Convert to CalendarEvent format
            return self._appointment_to_event(next_appointment)
            
        except (KeyError, ValueError, IndexError) as error:
            _LOGGER.error("Error processing appointment data: %s", error)
            return None

    async def async_get_events(self, hass, start_date, end_date):
        """Get all events in a specific time frame."""
        if not self.coordinator.data:
            return []
            
        events = []
        appointments = self.coordinator.data.get("appointments", [])
        
        if not appointments:
            return []
            
        for appointment in appointments:
            try:
                # Convert appointment to CalendarEvent
                event = self._appointment_to_event(appointment)
                
                if not event:
                    continue
                    
                # Check if event is within the requested date range
                # The start_date is the lower bound and applied to the event's end (exclusive)
                # The end_date is the upper bound and applied to the event's start (exclusive)
                if start_date < event.end and event.start < end_date:
                    events.append(event)
                    
            except (KeyError, ValueError) as error:
                _LOGGER.error("Error processing appointment for event: %s", error)
                
        return events

    def _appointment_to_event(self, appointment):
        """Convert an appointment to a calendar event."""
        try:
            # Get appointment date
            appointment_date_str = appointment["session"]["sessionDate"].split("T")[0]
            appointment_date = datetime.strptime(appointment_date_str, "%Y-%m-%d").date()
            
            # Get appointment time if available (default to noon if not specified)
            time_str = appointment.get("time", "").replace("T", "")
            if len(time_str) >= 4:
                hour = int(time_str[:2])
                minute = int(time_str[2:])
                start_dt = datetime.combine(appointment_date, time(hour=hour, minute=minute))
            else:
                # Default to noon if no specific time
                start_dt = datetime.combine(appointment_date, time(hour=12, minute=0))
                
            # Add timezone info to match Home Assistant's timezone
            start_dt = dt_util.as_local(start_dt)
            
            # Get procedure description - FIX: Define procedure before using it
            procedure = appointment.get("procedureDescription", "Blood Donation")
            
            # Make sure procedure is a string, defaulting to "Blood Donation" if missing
            if not procedure or not isinstance(procedure, str):
                procedure = "Blood Donation"
            
            # Set end time based on donation type - different procedures have different durations
            if "platelet" in procedure.lower() or "plt" in procedure.lower():
                # Platelet donations take around 90 minutes
                end_dt = start_dt + timedelta(minutes=90)
            elif "plasma" in procedure.lower() or "pls" in procedure.lower():
                # Plasma donations also take longer
                end_dt = start_dt + timedelta(minutes=60)
            else:
                # Whole blood donations take about 45 minutes
                end_dt = start_dt + timedelta(minutes=45)
            
            # Get venue details
            venue = appointment["session"]["venue"]["venueName"]
            
            # Format address
            address_lines = appointment["session"]["venue"]["address"]["lines"]
            postcode = appointment["session"]["venue"]["address"]["postcode"].strip()
            address = ", ".join([line.strip() for line in address_lines]) + ", " + postcode
            
            # Create description with all details
            description = f"Procedure: {procedure}\nVenue: {venue}\nAddress: {address}"
            
            # Create a unique identifier for the event
            uid = f"{appointment.get('appointmentId', '')}"
            if not uid:
                # If no appointment ID, create one from session and time
                session_id = appointment["session"].get("sessionId", "")
                uid = f"{session_id}_{appointment_date_str}_{time_str}"
            
            # Format the summary to just show the donation type
            if procedure.lower().endswith("donation"):
                summary = procedure
            else:
                summary = f"{procedure} Donation"
            
            return CalendarEvent(
                summary=summary,
                start=start_dt,
                end=end_dt,
                description=description,
                location=venue,
                uid=uid
            )
            
        except (KeyError, ValueError, TypeError) as error:
            _LOGGER.error("Error creating calendar event: %s", error)
            return None