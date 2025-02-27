"""Blood Donor Booking Helper Service with day of week support and response data."""
import logging
import voluptuous as vol
from datetime import datetime, timedelta, time, date
import async_timeout
import json
from typing import Dict, List, Tuple, Optional, Union, Any

from homeassistant.core import HomeAssistant, ServiceCall, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.components import persistent_notification

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_BOOKING_HELPER = "booking_helper"

# Days of the week mapping (0=Monday, 6=Sunday)
DAYS_OF_WEEK = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6
}

def validate_day_of_week(value: Optional[str]) -> Optional[str]:
    """Validate day of week input."""
    if value is None:
        return None
    lowercase_value = str(value).lower()
    if lowercase_value in DAYS_OF_WEEK:
        return lowercase_value
    raise vol.Invalid(f"Invalid day of week: {value}. Must be one of {list(DAYS_OF_WEEK.keys())}")

def normalize_time(time_input: Optional[str]) -> str:
    """Normalize time input to ensure it's in 'HH:MM' format."""
    if time_input is None:
        return "12:55"
    
    # Strip any seconds if present (like "12:55:00")
    if time_input.count(":") == 2:
        time_input = ":".join(time_input.split(":")[:2])
    
    # Remove any colons
    time_str = time_input.replace(":", "")
    
    # Pad with zeros if needed
    time_str = time_str.zfill(4)
    
    # Format as HH:MM
    return f"{time_str[:2]}:{time_str[2:]}"

# Validator that handles both required and optional parameters
def validate_optional_parameter(value: Any, validator: Any, default: Any = None) -> Any:
    """Validate optional parameter with a default value."""
    if value is None:
        return default
    return validator(value)

# Schema definition with more flexible validation
SERVICE_SCHEMA_BOOKING_HELPER = vol.Schema(
    {
        vol.Required("venue_id"): cv.string,
        vol.Optional("target_date"): vol.Any(cv.date, None),
        vol.Optional("target_day_of_week"): vol.Any(validate_day_of_week, None),
        vol.Optional("target_time"): vol.Coerce(str),
        vol.Optional("tolerance_hours"): vol.Coerce(float),
        vol.Optional("procedure_code"): vol.Coerce(str),
        vol.Optional("auto_book"): vol.Coerce(bool),
        vol.Optional("min_days_from_last_appointment"): vol.Coerce(int),
    },
    extra=vol.ALLOW_EXTRA
)

async def get_last_donation_date(hass: HomeAssistant, coordinator) -> Optional[date]:
    """
    Get the date of the last donation or future appointment from existing appointments.
    This function specifically searches for the *latest* appointment (past or future)
    to ensure we respect minimum days between appointments.
    """
    # Ensure we have the most recent data
    if not coordinator.data or not coordinator.last_update_success:
        await coordinator.async_refresh()
    
    if not coordinator.data:
        _LOGGER.debug("No coordinator data available")
        return None
        
    # Check existing appointments
    appointments = coordinator.data.get("appointments", [])
    
    if not appointments:
        _LOGGER.debug("No appointments found in coordinator data")
        return datetime.now().date() - timedelta(days=60)
    
    _LOGGER.debug(f"Found {len(appointments)} appointments to check")
    
    # Log all appointments for debugging
    for apt in appointments:
        try:
            apt_date_str = apt["session"]["sessionDate"].split("T")[0]
            _LOGGER.debug(f"Appointment: {apt_date_str}")
        except (KeyError, IndexError):
            _LOGGER.debug(f"Appointment data format error: {apt}")
    
    # Get the latest appointment (both past and future)
    try:
        # First convert all appointments to dates
        appointment_dates = []
        for apt in appointments:
            try:
                apt_date_str = apt["session"]["sessionDate"].split("T")[0]
                apt_date = datetime.strptime(apt_date_str, "%Y-%m-%d").date()
                appointment_dates.append(apt_date)
            except (KeyError, ValueError, IndexError) as e:
                _LOGGER.warning(f"Error parsing appointment date: {e}")
        
        if not appointment_dates:
            _LOGGER.debug("No appointment dates could be parsed")
            return datetime.now().date() - timedelta(days=60)
        
        # Get the latest appointment date (regardless of past or future)
        latest_appointment = max(appointment_dates)
        _LOGGER.debug(f"Latest appointment found: {latest_appointment}")
        
        return latest_appointment
        
    except Exception as e:
        _LOGGER.warning(f"Error determining last donation date: {str(e)}")
        return datetime.now().date() - timedelta(days=60)

async def get_sessions_for_date(
    hass: HomeAssistant, 
    coordinator, 
    venue_id: str, 
    date_str: str,
    procedure_code: str = ""
) -> List[Dict]:
    """Get sessions for a specific date."""
    with async_timeout.timeout(30):
        headers = {"Authorization": f"Bearer {coordinator.api._access_token}"}
        session = coordinator.api._session
        
        # We need to set start_date and end_date to be the same date
        params = {
            "startDate": date_str,
            "endDate": date_str
        }
        
        if procedure_code:
            params["procedureCode"] = procedure_code
        
        url = f"https://my.blood.co.uk/api/sessions/{venue_id}"
        _LOGGER.debug("Making request to %s with params %s", url, params)
        
        response = await session.get(url, headers=headers, params=params)
        
        if response.status == 401:
            # Token expired, try to login again
            _LOGGER.debug("Token expired, logging in again")
            if await coordinator.api.login():
                return await get_sessions_for_date(hass, coordinator, venue_id, date_str, procedure_code)
            _LOGGER.error("Re-login failed")
            return []
        
        if response.status != 200:
            _LOGGER.error("Failed to get sessions: %s", await response.text())
            return []
        
        data = await response.json()
        return data.get("sessions", [])

async def get_slots_for_session(
    hass: HomeAssistant, 
    coordinator, 
    session_id: str, 
    session_date: str,
    procedure_code: str = ""
) -> List[Dict]:
    """Get available slots for a specific session."""
    with async_timeout.timeout(30):
        headers = {"Authorization": f"Bearer {coordinator.api._access_token}"}
        session_obj = coordinator.api._session
        
        url = f"https://my.blood.co.uk/api/appointments/{session_id}/slots"
        params = {
            "sessionDate": session_date
        }
        
        if procedure_code:
            params["procedureCode"] = procedure_code
        
        _LOGGER.debug("Making request to %s with params %s", url, params)
        
        response = await session_obj.get(url, headers=headers, params=params)
        
        if response.status == 401:
            # Token expired, try to login again
            _LOGGER.debug("Token expired, logging in again")
            if await coordinator.api.login():
                return await get_slots_for_session(hass, coordinator, session_id, session_date, procedure_code)
            _LOGGER.error("Re-login failed")
            return []
        
        if response.status != 200:
            _LOGGER.error("Failed to get session slots: %s", await response.text())
            return []
        
        data = await response.json()
        return data.get("slots", [])

async def book_appointment(
    hass: HomeAssistant,
    coordinator,
    session_id: str,
    session_date: str,
    session_time: str,
    venue_id: str,
    procedure_code: str = ""
) -> Dict:
    """Book an appointment."""
    try:
        with async_timeout.timeout(30):
            headers = {
                "Authorization": f"Bearer {coordinator.api._access_token}",
                "Content-Type": "application/json"
            }
            session_obj = coordinator.api._session
            
            # Build the request payload
            payload = {
                "sessionID": session_id,
                "sessionDate": session_date,
                "sessionTime": session_time,
                "venueId": venue_id,
                "procedureCode": procedure_code,
                "platform": "web"
            }
            
            _LOGGER.debug("Making request to book appointment with payload: %s", payload)
            
            response = await session_obj.post(
                "https://my.blood.co.uk/api/appointments/book",
                headers=headers,
                json=payload
            )
            
            if response.status == 401:
                # Token expired, try to login again
                _LOGGER.debug("Token expired, logging in again")
                if await coordinator.api.login():
                    return await book_appointment(hass, coordinator, session_id, session_date, 
                                                session_time, venue_id, procedure_code)
                _LOGGER.error("Re-login failed")
                return {"success": False, "error": "Authentication failed"}
            
            response_text = await response.text()
            
            if response.status != 200:
                _LOGGER.error("Failed to book appointment: %s", response_text)
                return {"success": False, "error": response_text}
            
            # Parse the response
            try:
                data = await response.json()
                status = data.get("status", "")
                
                if status == "B":
                    return {"success": True, "data": data}
                else:
                    return {"success": False, "error": f"Booking returned status: {status}"}
                
            except json.JSONDecodeError:
                _LOGGER.error("Failed to parse booking response")
                return {"success": False, "error": "Failed to parse booking response"}
            
    except Exception as error:
        _LOGGER.exception("Error booking appointment: %s", error)
        return {"success": False, "error": str(error)}

async def setup_booking_helper_service(hass: HomeAssistant) -> None:
    """Set up booking helper service for Blood Donor integration."""
    _LOGGER.debug("Setting up Blood Donor booking helper service")

    # Check if service is already registered
    if hass.services.has_service(DOMAIN, SERVICE_BOOKING_HELPER):
        return

    @callback
    async def async_booking_helper_service(call: ServiceCall) -> Dict:
        """Find and optionally book the closest appointment to a target time.
        Returns a dictionary with response data.
        """
        _LOGGER.debug("Booking helper service called with: %s", call.data)
        
        # Initialize response data structure
        response_data = {
            "success": False,
            "message": "",
            "appointment": None,
            "error": None
        }
        
        # Normalize and set default values
        data = {
            "venue_id": call.data.get("venue_id"),
            "target_date": call.data.get("target_date"),
            "target_day_of_week": call.data.get("target_day_of_week"),
            "target_time": normalize_time(call.data.get("target_time")),
            "tolerance_hours": call.data.get("tolerance_hours", 2.0),
            "procedure_code": call.data.get("procedure_code", ""),
            "auto_book": call.data.get("auto_book", False),
            "min_days_from_last_appointment": call.data.get("min_days_from_last_appointment", 14)
        }
        
        # Validate the input
        try:
            validated_data = SERVICE_SCHEMA_BOOKING_HELPER(data)
        except vol.Invalid as e:
            error_msg = f"Invalid booking helper parameters: {e}"
            _LOGGER.error(error_msg)
            persistent_notification.async_create(
                error_msg,
                title="Blood Donor Booking Helper Error",
                notification_id="blood_donor_booking_helper_invalid_params"
            )
            response_data["error"] = error_msg
            return response_data
        
        # Ensure either target_date or target_day_of_week is provided
        if not (validated_data.get("target_date") or validated_data.get("target_day_of_week")):
            error_msg = "Either target_date or target_day_of_week must be provided"
            _LOGGER.error(error_msg)
            hass.components.persistent_notification.async_create(
                error_msg,
                title="Blood Donor Booking Helper Error",
                notification_id="blood_donor_booking_helper_missing_date"
            )
            response_data["error"] = error_msg
            return response_data
        
        coordinators = hass.data.get(DOMAIN, {})
        if not coordinators:
            error_msg = "No Blood Donor coordinators found"
            _LOGGER.warning(error_msg)
            response_data["error"] = error_msg
            return response_data
        
        venue_id = validated_data.get("venue_id")
        
        # Get the first coordinator to access appointments and API
        coordinator = next(iter(coordinators.values()))
        
        # Parse the time string (now already normalized)
        target_time_str = validated_data.get("target_time")
        parts = target_time_str.split(":")
        target_time = time(int(parts[0]), int(parts[1]))
            
        tolerance_hours = validated_data.get("tolerance_hours", 2.0)
        procedure_code = validated_data.get("procedure_code", "")
        auto_book = validated_data.get("auto_book", False)
        min_days_from_last = validated_data.get("min_days_from_last_appointment", 14)
        
        # Determine the target date based on whether a specific date or day of week was provided
        if validated_data.get("target_date"):
            target_date = validated_data.get("target_date")
            _LOGGER.debug("Using provided target date: %s", target_date)
        else:
            # Calculate the date for the next occurrence of the specified day of week
            day_of_week = validated_data.get("target_day_of_week")
            target_day_idx = DAYS_OF_WEEK[day_of_week]
            
        # Find the last donation date first
        last_donation_date = await get_last_donation_date(hass, coordinator)
        _LOGGER.debug(f"Latest appointment found: {last_donation_date}")

        # Calculate the earliest allowed date based on the minimum days constraint
        earliest_allowed_date = (last_donation_date + timedelta(days=min_days_from_last)) if last_donation_date else datetime.now().date()
        # Make sure we're at least looking at today or later
        earliest_allowed_date = max(earliest_allowed_date, datetime.now().date())
        _LOGGER.debug(f"Earliest allowed date (exactly {min_days_from_last} days after latest appointment): {earliest_allowed_date}")
        _LOGGER.debug(f"Day of week for earliest allowed date: {earliest_allowed_date.strftime('%A')}")

        # Find the next occurrence of the desired day of the week starting from earliest allowed date
        current_date = earliest_allowed_date
        current_day_idx = current_date.weekday()  # 0=Monday, 6=Sunday
        target_day_idx = DAYS_OF_WEEK[day_of_week]  # The day user requested (e.g., "wednesday" = 2)
                    
        _LOGGER.debug(f"Current day index: {current_day_idx}, Target day index: {target_day_idx}")

        # Calculate days to add to reach the target day of week
        if current_day_idx == target_day_idx:
            # If the earliest allowed date is already the target day of week, use it
            days_to_add = 0
            _LOGGER.debug(f"Earliest allowed date is already a {day_of_week.capitalize()}, using it")
        else:
            # Calculate days to add to get to the next occurrence of target day
            days_to_add = (target_day_idx - current_day_idx) % 7
            if days_to_add < 0:
                days_to_add += 7
            _LOGGER.debug(f"Adding {days_to_add} days to reach next {day_of_week.capitalize()}")

        target_date = current_date + timedelta(days=days_to_add)
        _LOGGER.debug(f"Final target date: {target_date} ({target_date.strftime('%A')})")

        # Calculate time window
        target_datetime = datetime.combine(target_date, target_time)
        start_datetime = target_datetime - timedelta(hours=tolerance_hours)
        end_datetime = target_datetime + timedelta(hours=tolerance_hours)
        
        # Ensure we're only looking at the specified date
        start_datetime = max(start_datetime, datetime.combine(target_date, time(0, 0, 0)))
        end_datetime = min(end_datetime, datetime.combine(target_date, time(23, 59, 59)))
        
        _LOGGER.debug("Looking for appointments on %s between %s and %s", 
                      target_date, start_datetime.time(), end_datetime.time())
        
        # Format date string for API
        target_date_str = f"{target_date.isoformat()}T00:00:00"
        
        try:
            # Use the API client from the coordinator to make the request
            if not coordinator.api._access_token:
                await coordinator.api.login()
                
            if not coordinator.api._access_token:
                error_msg = "Failed to login to Blood Donor service"
                _LOGGER.error(error_msg)
                response_data["error"] = error_msg
                return response_data
                
            # Step 1: Get sessions for the target date
            sessions = await get_sessions_for_date(hass, coordinator, venue_id, target_date_str, procedure_code)
            if not sessions:
                message = f"No sessions available for {target_date}."
                _LOGGER.warning(message)
                hass.components.persistent_notification.async_create(
                    message,
                    title="Blood Donor Booking Helper",
                    notification_id="blood_donor_booking_helper"
                )
                response_data["message"] = message
                response_data["error"] = "No sessions available"
                return response_data
            
            # Step 2: Find sessions with available slots
            available_sessions = []
            for session in sessions:
                session_id = session.get("sessionId", "")
                session_date = session.get("sessionDate", "")
                
                # Check if this session has any available slots
                has_availability = False
                for period in session.get("periods", []):
                    if int(period.get("availableSlots", 0)) > 0:
                        has_availability = True
                        break
                
                if has_availability:
                    available_sessions.append({
                        "session_id": session_id,
                        "session_date": session_date,
                    })
            
            if not available_sessions:
                message = f"No available appointment slots found for {target_date}."
                _LOGGER.warning(message)
                hass.components.persistent_notification.async_create(
                    message,
                    title="Blood Donor Booking Helper",
                    notification_id="blood_donor_booking_helper"
                )
                response_data["message"] = message
                response_data["error"] = "No available slots"
                return response_data
            
            # Step 3: Get detailed slot times for available sessions
            all_slots = []
            
            for session_info in available_sessions:
                slots = await get_slots_for_session(
                    hass, 
                    coordinator, 
                    session_info["session_id"], 
                    session_info["session_date"],
                    procedure_code
                )
                
                if slots:
                    for slot in slots:
                        slot_time_str = slot.get("time", "").replace("T", "")
                        if len(slot_time_str) >= 4:
                            try:
                                # Parse the time string
                                hour = int(slot_time_str[:2])
                                minute = int(slot_time_str[2:])
                                slot_time = time(hour, minute)
                                slot_datetime = datetime.combine(target_date, slot_time)
                                
                                # Only include slots within our tolerance window
                                if start_datetime <= slot_datetime <= end_datetime:
                                    slot["session_id"] = session_info["session_id"]
                                    slot["session_date"] = session_info["session_date"]
                                    slot["slot_datetime"] = slot_datetime
                                    slot["time_difference"] = abs((slot_datetime - target_datetime).total_seconds() / 3600)
                                    all_slots.append(slot)
                            except (ValueError, TypeError):
                                _LOGGER.warning("Invalid time format in slot: %s", slot_time_str)
            
            if not all_slots:
                message = f"No available slots found within {tolerance_hours} hours of {target_time} on {target_date}."
                _LOGGER.warning(message)
                hass.components.persistent_notification.async_create(
                    message,
                    title="Blood Donor Booking Helper",
                    notification_id="blood_donor_booking_helper"
                )
                response_data["message"] = message
                response_data["error"] = "No slots within tolerance window"
                return response_data
            
            # Step 4: Sort by time difference from target
            all_slots.sort(key=lambda x: x["time_difference"])
            
            # Step 5: Get the best match
            best_slot = all_slots[0]
            best_time_str = best_slot.get("time", "").replace("T", "")
            best_time_formatted = f"{best_time_str[:2]}:{best_time_str[2:]}" if len(best_time_str) >= 4 else best_time_str
            procedure = best_slot.get("procedureDescription", "")
            
            # Prepare appointment data for response
            appointment_data = {
                "date": target_date.isoformat(),
                "day_of_week": target_date.strftime("%A"),
                "time": best_time_formatted,
                "venue_id": venue_id,
                "procedure": procedure,
                "session_id": best_slot["session_id"],
                "session_date": best_slot["session_date"],
                "session_time": best_slot["time"],
                "time_difference": f"{best_slot['time_difference']:.1f}"
            }
            
            # Create message with the result
            if auto_book:
                # Automatically book the appointment
                session_id = best_slot["session_id"]
                session_date = best_slot["session_date"]
                session_time = best_slot["time"]
                
                booking_result = await book_appointment(
                    hass,
                    coordinator,
                    session_id,
                    session_date,
                    session_time,
                    venue_id,
                    procedure_code
                )
                
                if booking_result.get("success", False):
                    message = f"## Appointment Booked Successfully!\n\n"
                    message += f"**Date:** {target_date}\n"
                    message += f"**Time:** {best_time_formatted}\n"
                    message += f"**Procedure:** {procedure}\n"
                    message += f"**Venue ID:** {venue_id}\n\n"
                    message += "This was the closest available appointment to your requested time of "
                    message += f"{target_time.strftime('%H:%M')}.\n\n"
                    message += "Difference from target time: "
                    message += f"{best_slot['time_difference']:.1f} hours"
                    
                    # Notify user
                    hass.components.persistent_notification.async_create(
                        message,
                        title="Blood Donor Appointment Booked",
                        notification_id="blood_donor_booking_helper_success"
                    )
                    
                    # Set response data
                    response_data["success"] = True
                    response_data["message"] = "Appointment booked successfully"
                    response_data["appointment"] = appointment_data
                    
                    # Also trigger a refresh to update all entities with the new appointment
                    await coordinator.async_refresh()
                else:
                    error_message = booking_result.get("error", "Unknown error")
                    message = f"Failed to book appointment: {error_message}\n\n"
                    message += f"Attempted to book: {target_date} at {best_time_formatted}\n"
                    message += "Please try booking manually or try again later."
                    
                    hass.components.persistent_notification.async_create(
                        message,
                        title="Blood Donor Booking Failed",
                        notification_id="blood_donor_booking_helper_failed"
                    )
                    
                    response_data["success"] = False
                    response_data["message"] = f"Failed to book appointment: {error_message}"
                    response_data["error"] = error_message
                    response_data["appointment"] = appointment_data  # Still return the found appointment
            else:
                # Just show the best match without booking
                message = f"## Best Available Appointment\n\n"
                message += f"**Date:** {target_date} ({target_date.strftime('%A')})\n"
                message += f"**Time:** {best_time_formatted}\n"
                message += f"**Procedure:** {procedure}\n"
                message += f"**Venue ID:** {venue_id}\n\n"
                message += "This is the closest available appointment to your requested time of "
                message += f"{target_time.strftime('%H:%M')}.\n\n"
                message += "Difference from target time: "
                message += f"{best_slot['time_difference']:.1f} hours\n\n"
                
                # Add booking service call
                message += "To book this appointment, call the service:\n"
                message += "```yaml\nservice: blood_donor.book_appointment\ndata:\n"
                message += f"  session_id: \"{best_slot['session_id']}\"\n"
                message += f"  session_date: \"{best_slot['session_date']}\"\n"
                message += f"  session_time: \"{best_slot['time']}\"\n"
                message += f"  venue_id: \"{venue_id}\"\n"
                if procedure_code:
                    message += f"  procedure_code: \"{procedure_code}\"\n"
                message += "```\n\n"
                
                # Add option to auto-book
                message += "Or run the booking helper with auto_book enabled:\n"
                message += "```yaml\nservice: blood_donor.booking_helper\ndata:\n"
                message += f"  venue_id: \"{venue_id}\"\n"
                message += f"  target_date: \"{target_date}\"\n"
                message += f"  target_time: \"{target_time}\"\n"
                message += f"  tolerance_hours: {tolerance_hours}\n"
                if procedure_code:
                    message += f"  procedure_code: \"{procedure_code}\"\n"
                message += "  auto_book: true\n"
                message += "```"
                
                hass.components.persistent_notification.async_create(
                    message,
                    title="Blood Donor Best Available Appointment",
                    notification_id="blood_donor_booking_helper_result"
                )
                
                # Set response data
                response_data["success"] = True
                response_data["message"] = "Found best available appointment (not booked)"
                response_data["appointment"] = appointment_data
                
        except Exception as error:
            error_msg = f"An error occurred while finding the best appointment: {str(error)}"
            _LOGGER.exception("Error in booking helper service: %s", error)
            hass.components.persistent_notification.async_create(
                error_msg,
                title="Blood Donor Booking Helper Error",
                notification_id="blood_donor_booking_helper_error"
            )
            response_data["success"] = False
            response_data["error"] = str(error)

        _LOGGER.debug("Booking helper processing completed for date: %s", target_date)
        return response_data
        
    hass.services.async_register(
        DOMAIN,
        SERVICE_BOOKING_HELPER,
        async_booking_helper_service,
        schema=SERVICE_SCHEMA_BOOKING_HELPER,
        supports_response=True
    )
    
    _LOGGER.debug("Blood Donor booking helper service registered")